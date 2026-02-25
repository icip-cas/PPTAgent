import base64
import os
import re
import sys
import uuid
from pathlib import Path

from fastmcp import FastMCP
from markitdown import MarkItDown
from PIL import Image

from deeppresenter.utils.log import set_logger, warning
from deeppresenter.utils.mineru_api import parse_pdf_offline, parse_pdf_online

mcp = FastMCP(name="Any2Markdown")

IMAGE_EXTENSIONS = [
    "bmp",
    "jpg",
    "jpeg",
    "pgm",
    "png",
    "ppm",
    "tif",
    "tiff",
    "webp",
]
MINERU_API_URL = os.getenv("MINERU_API_URL", None)
MINERU_API_KEY = os.getenv("MINERU_API_KEY", None)


@mcp.tool()
async def convert_to_markdown(file_path: str, output_folder: str) -> dict:
    """Convert a file to markdown, it could accept pdf, docx, doc, etc.
    Args:
        file_path: The path of the file to be converted
        output_folder: The folder to save the converted markdown and images, should be empty or not exist

    Returns:
        The converted results, with file saved to the specified path
    """

    output_path = Path(output_folder)
    output_path.mkdir(parents=True, exist_ok=True)
    assert len(list(output_path.iterdir())) == 0, (
        f"Output folder {output_folder} is not empty"
    )
    assert os.path.exists(file_path), f"Error: file {file_path} does not exist"

    markdown_file = output_path / f"{Path(file_path).stem}.md"

    if file_path.lower().endswith(".pdf") and (MINERU_API_KEY or MINERU_API_URL):
        if MINERU_API_KEY:
            await parse_pdf_online(file_path, str(output_path), MINERU_API_KEY)
        elif MINERU_API_URL:
            await parse_pdf_offline(file_path, str(output_path), MINERU_API_URL)
        for f in output_path.glob("*"):
            if f.name.lower().endswith(".md"):
                os.rename(f, str(markdown_file))
            elif f.name.lower().endswith((".json", ".pdf")):
                os.remove(f)
        with open(str(markdown_file), encoding="utf-8") as f:
            markdown = f.read()
    else:
        conver_result = MarkItDown().convert_local(file_path, keep_data_uris=True)
        markdown = parse_base64_images(
            conver_result.text_content, output_path / "images"
        )

    for match in re.findall(r"!\[.*?\]\((.*?)\)", markdown):
        local_path = match.split()[0].strip("\"'")
        p = Path(local_path)
        if (output_path / local_path).exists():
            p = output_path / local_path
        if p.exists():
            markdown = markdown.replace(local_path, str(p.resolve()))
    with open(str(markdown_file), "w", encoding="utf-8") as f:
        f.write(markdown)

    images = output_path.glob("images/*")
    images_with_info = []
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                images_with_info.append((img_path, *img.size))
        except Exception:
            continue

    images_with_info.sort(key=lambda x: int(x[1]), reverse=True)

    return {
        "success": True,
        "markdown_file": str(markdown_file),
        "images": f"Found {len(images_with_info)} images\n"
        + "".join([f"- {img[0]}: {img[1]}x{img[2]}\n" for img in images_with_info]),
    }


def parse_base64_images(markdown: str, image_dir: Path) -> str:
    """Save base64 images to local, and convert those links to local paths"""
    image_dir.mkdir(exist_ok=True, parents=True)
    for image_match in re.finditer(
        r"!\[([^\]]*)\]\((data:image/([^;]+);base64,([^)]+))\)", markdown
    ):
        _, data_uri, image_format, base64_data = image_match.groups()

        if image_format.lower() not in IMAGE_EXTENSIONS:
            markdown = markdown.replace(image_match.group(0), "")
            warning(f"Unsupported image format: {image_format}, image will be ignored")
            continue

        image_data = base64.b64decode(base64_data)
        image_path = image_dir / (uuid.uuid4().hex[:4] + "." + image_format)

        with open(image_path, "wb") as f:
            f.write(image_data)

        # Replace data URI with relative path
        markdown = markdown.replace(data_uri, str(image_path))

    return markdown


if __name__ == "__main__":
    assert len(sys.argv) == 2, "Usage: python any2markdown.py <workspace>"
    work_dir = Path(sys.argv[1])
    assert work_dir.exists(), f"Workspace {work_dir} does not exist."
    os.chdir(work_dir)
    set_logger(
        f"any2markdown-{work_dir.stem}", work_dir / ".history" / "any2markdown.log"
    )

    mcp.run(show_banner=False)
