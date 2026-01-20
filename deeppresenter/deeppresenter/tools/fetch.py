"""Web content fetching tool"""

import asyncio
import re
from pathlib import Path

import httpx
import markdownify
from appcore import mcp
from fake_useragent import UserAgent
from PIL import Image
from playwright.async_api import TimeoutError
from trafilatura import extract

from deeppresenter.utils.constants import MCP_CALL_TIMEOUT, RETRY_TIMES
from deeppresenter.utils.webview import PlaywrightConverter

FAKE_UA = UserAgent()


@mcp.tool()
async def fetch_url(url: str, body_only: bool = True) -> str:
    """
    Fetch web page content

    Args:
        url: Target URL
        body_only: If True, return only main content; otherwise return full page, default True
    """

    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        try:
            resp = await client.head(url)

            # Some servers may return error on HEAD; fall back to GET
            if resp.status_code >= 400:
                resp = await client.get(url, stream=True)

            content_type = resp.headers.get("Content-Type", "").lower()
            content_dispo = resp.headers.get("Content-Disposition", "").lower()

            if "attachment" in content_dispo or "filename=" in content_dispo:
                return f"URL {url} is a downloadable file (Content-Disposition: {content_dispo})"

            if not content_type.startswith("text/html"):
                return f"URL {url} returned {content_type}, not a web page"

        # Do not block Playwright: ignore errors from httpx for banned/blocked HEAD requests
        except Exception:
            pass

    async with PlaywrightConverter() as converter:
        try:
            await converter.page.goto(
                url, wait_until="domcontentloaded", timeout=MCP_CALL_TIMEOUT // 2 * 1000
            )
            html = await converter.page.content()
        except TimeoutError:
            return f"Timeout when loading URL: {url}"
        except Exception as e:
            return f"Failed to load URL {url}: {e}"

    markdown = markdownify.markdownify(html, heading_style=markdownify.ATX)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    if body_only:
        result = extract(
            html,
            output_format="markdown",
            with_metadata=True,
            include_links=True,
            include_images=True,
            include_tables=True,
        )
        return result or markdown

    return markdown


@mcp.tool()
async def download_file(url: str, output_path: str) -> str:
    """
    Download a file from a URL and save it to a local path.
    """
    # Create directory if it doesn't exist
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    for retry in range(RETRY_TIMES):
        try:
            await asyncio.sleep(retry)
            async with httpx.AsyncClient(
                headers={"User-Agent": FAKE_UA.random},
                follow_redirects=True,
                verify=False,
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    with open(output_path, "wb") as f:
                        async for chunk in response.aiter_bytes(8192):
                            f.write(chunk)
                    break
        except:
            pass
    else:
        return f"Failed to download file from {url}"

    result = f"File downloaded to {output_path},from {url}"
    if output_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
        try:
            with Image.open(output_path) as img:
                width, height = img.size
                # Convert WEBP to PNG
                if img.format == 'WEBP':
                    png_path = str(Path(output_path).with_suffix('.png'))
                    img.save(png_path, format="PNG")
                    Path(output_path).unlink()
                    output_path = png_path
                    result += f"\nFile re-downloaded to {output_path}"
                result += f" (resolution: {width}x{height})"
        except Exception as e:
            return f"The provided URL does not point to a valid image file: {e}"
    return result
