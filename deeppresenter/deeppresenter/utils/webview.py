import asyncio
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Literal

from fake_useragent import UserAgent
from pdf2image import convert_from_path
from playwright.async_api import async_playwright
from pypdf import PdfWriter

from deeppresenter.utils.constants import PACKAGE_DIR, PDF_OPTIONS
from deeppresenter.utils.log import error, info

FAKE_UA = UserAgent()

LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-blink-features=AutomationControlled",
]

ANTI_DETECTION = """
() => {
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    if (!window.chrome) { window.chrome = { runtime: {} }; }
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
}
"""

ASPECT_RATIOS = {
    "16:9": {"width": "1280px", "height": "720px"},
    "4:3": {"width": "960px", "height": "720px"},
    "A1": {"width": "2244px", "height": "3178px"},
    "A2": {"width": "1587px", "height": "2244px"},
    "A3": {"width": "1122px", "height": "1587px"},
    "A4": {"width": "794px", "height": "1123px"},
}


class PlaywrightConverter:
    _playwright = None
    _browser = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.context = None
        self.page = None

    async def __aenter__(self):
        """Async context manager entry"""
        async with PlaywrightConverter._lock:
            if PlaywrightConverter._browser is None:
                PlaywrightConverter._playwright = await async_playwright().start()
                PlaywrightConverter._browser = (
                    await PlaywrightConverter._playwright.chromium.launch(
                        headless=True, args=LAUNCH_ARGS
                    )
                )

        self.context = await PlaywrightConverter._browser.new_context(
            user_agent=FAKE_UA.random,
            bypass_csp=True,
        )
        await self.context.add_init_script(ANTI_DETECTION)
        self.page = await self.context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit, only close context"""
        if self.context:
            await self.context.close()

    async def convert_to_pdf(
        self,
        html_files: list[str | Path],
        output_pdf: Path | str,
        aspect_ratio: Literal["16:9", "4:3", "A1", "A2", "A3", "A4"],
        error_sink: list[str] | None = None,
    ) -> Path:
        if isinstance(output_pdf, str):
            output_pdf = Path(output_pdf)
        pdf_files = [tempfile.mkstemp(suffix=".pdf")[1] for _ in range(len(html_files))]
        folder = output_pdf.parent / f".slide_images-pdf-{output_pdf.stem}"
        folder.mkdir(exist_ok=True, parents=True)

        page = await self.context.new_page()
        if error_sink is not None:
            page.on(
                "pageerror",
                lambda exc: error_sink.append(f"Page error: {exc}"),
            )
            page.on(
                "console",
                lambda msg: (
                    error_sink.append(f"Console error: {msg.text}")
                    if msg.type == "error"
                    else None
                ),
            )
        try:
            for html, pdf in zip(sorted(html_files), pdf_files):
                await page.goto(Path(html).resolve().as_uri(), wait_until="networkidle")
                await page.pdf(path=pdf, **PDF_OPTIONS, **ASPECT_RATIOS[aspect_ratio])
        except Exception as e:
            error(f"Failed to convert HTML to PDF: {e}")
            raise e
        finally:
            await page.close()

        with PdfWriter() as merger:
            for pdf_file in pdf_files:
                merger.append(pdf_file)

            with open(output_pdf, "wb") as f:
                merger.write(f)

        for idx, page in enumerate(convert_from_path(output_pdf, dpi=100)):
            page.save(folder / f"slide_{(idx + 1):02d}.jpg")
        info(f"Converted PDF saved at: {output_pdf}")
        return folder


async def convert_html_to_pptx(
    html_inputs: Path | str | Iterable[Path | str],
    output_pptx: Path | str | None = None,
    aspect_ratio: Literal["16:9", "4:3", "A1", "A2", "A3", "A4"] = "16:9",
    soft: bool = False,
):
    script_path = PACKAGE_DIR / "html2pptx" / "html2pptx_cli.js"
    if not script_path.exists():
        raise FileNotFoundError(f"html2pptx CLI not found at {script_path}")

    validate_only = output_pptx is None
    output_path = None if validate_only else Path(output_pptx)

    html_dir: Path | None = None
    html_files: list[str] = []
    if isinstance(html_inputs, (str, Path)):
        input_path = Path(html_inputs)
        if not input_path.exists():
            raise FileNotFoundError(f"HTML input does not exist: {input_path}")
        if input_path.is_dir():
            html_dir = input_path
        else:
            html_files = [str(input_path.resolve())]
    else:
        for item in html_inputs:
            item_path = Path(item)
            if not item_path.exists():
                raise FileNotFoundError(f"HTML input does not exist: {item_path}")
            if item_path.is_dir():
                if html_dir is not None or html_files:
                    raise ValueError("html_inputs cannot mix directories and files")
                html_dir = item_path
            else:
                html_files.append(str(item_path.resolve()))

    if html_dir is None and not html_files:
        raise ValueError("No HTML inputs provided")

    cmd = ["node", str(script_path), "--layout", aspect_ratio]
    if html_dir is not None:
        cmd.extend(["--html_dir", str(html_dir.resolve())])
    else:
        for html_file in html_files:
            cmd.extend(["--html", html_file])

    if validate_only:
        cmd.append("--validate")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--output", str(output_path)])

    if soft:
        cmd.append("--soft")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        env=os.environ.copy(),
        cwd=PACKAGE_DIR.parent.parent,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        details = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()
        if "Cannot find module 'pptxgenjs'" in details:
            raise RuntimeError(
                "html2pptx dependency 'pptxgenjs' is not installed. "
                "Run `npm install` in the repo root."
            )
        raise RuntimeError(f"html2pptx failed: {details.split('at html2pptx (')[0]}")
