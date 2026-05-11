import math
import os
import re
import shutil
import warnings
from pathlib import Path

from fastmcp import FastMCP
from PIL import Image
from pptagent_pptx import Presentation

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.log import debug, set_logger, warning

warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="fastmcp.tools.tool"
)

Image.MAX_IMAGE_PIXELS = None  # only reading metadata, no actual decompression

mcp = FastMCP(name="Task")

CONFIG = DeepPresenterConfig.load_from_file(os.getenv("CONFIG_FILE"))


def _rewrite_image_link(match: re.Match[str], md_dir: Path) -> str:
    alt_text = match.group(1)
    target = match.group(2).strip()
    if not target:
        return match.group(0)
    parts = re.match(r"([^\s]+)(.*)", target)
    if not parts:
        return match.group(0)
    local_path = parts.group(1).strip("\"'")
    rest = parts.group(2)
    p = Path(local_path)
    if not p.is_absolute() and (md_dir / local_path).exists():
        p = md_dir / local_path
    if not p.exists():
        return match.group(0)

    updated_alt = alt_text
    try:
        with Image.open(p) as img:
            width, height = img.size
        if width > 0 and height > 0 and not re.search(r"\b\d+:\d+\b", updated_alt):
            factor = math.gcd(width, height)
            ratio = f"{width // factor}:{height // factor}"
            updated_alt = f"{updated_alt}, {ratio}" if updated_alt else ratio
    except Exception as e:
        warning(f"Failed to get image size for {p}: {e}")

    # ? since slides were placed in an independent folder, we convert image path to absolute path to avoid broken links
    new_path = p.resolve().as_posix()
    return f"![{updated_alt}]({new_path}{rest})"


@mcp.tool(exclude_args=["agent_name"])
def finalize(outcome: str, agent_name: str = "") -> str:
    """
    When all tasks are finished, call this function to finalize the loop.
    Args:
        outcome (str): The path to the final outcome file or directory.
    """
    # here we conduct some final checks on agent's outcome
    path = Path(outcome)
    assert path.exists(), f"Outcome {outcome} does not exist"

    if agent_name == "Planner":
        assert path.suffix == ".json", (
            f"Outline file should be a JSON file, got {path.suffix}"
        )

    elif agent_name == "Research":
        md_dir = path.parent
        assert path.suffix == ".md", (
            f"Outcome file should be a markdown file, got {path.suffix}"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        try:
            content = re.sub(
                r"!\[(.*?)\]\((.*?)\)",
                lambda match: _rewrite_image_link(match, md_dir),
                content,
            )
            shutil.copyfile(path, md_dir / ("." + path.name))
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            warning(f"Failed to rewrite image links: {e}")

    elif agent_name == "PPTAgent":
        assert path.is_file() and path.suffix == ".pptx", (
            f"Outcome file should be a pptx file, got {path.suffix}"
        )
        prs = Presentation(str(path))
        if len(prs.slides) <= 0:
            return "PPTX file should contain at least one slide"
    elif agent_name == "Design":
        html_files = list(path.glob("*.html"))
        if len(html_files) <= 0:
            return "Outcome path should be a directory containing HTML files"
        if not all(f.stem.startswith("slide_") for f in html_files):
            return "All HTML files should start with 'slide_'"
    elif path.is_file() and agent_name:
        if path.stat().st_size == 0:
            return f"Outcome file for {agent_name} is empty"

    debug(f"Agent {agent_name} finalized the outcome: {outcome}")
    return outcome


if __name__ == "__main__":
    work_dir = Path(os.environ["WORKSPACE"])
    assert work_dir.exists(), f"Workspace {work_dir} does not exist."
    os.chdir(work_dir)
    set_logger(f"task-{work_dir.stem}", work_dir / ".history" / "task.log")

    mcp.run(show_banner=False)
