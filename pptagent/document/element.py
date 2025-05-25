import hashlib
import re
from dataclasses import dataclass
from typing import Any, Optional, abstractmethod

from bs4 import BeautifulSoup
from jinja2 import Environment, StrictUndefined
from mistune import html as markdown
from PIL import Image

from pptagent.llms import LLM, AsyncLLM
from pptagent.utils import (
    edit_distance,
    get_logger,
    markdown_table_to_image,
    package_join,
    pbasename,
    pexists,
    pjoin,
)

env = Environment(undefined=StrictUndefined)

IMAGE_PARSING_REGEX = re.compile(r"\((.*?)\)")
TABLE_PARSING_PROMPT = env.from_string(
    open(package_join("prompts", "table_parsing.txt")).read()
)
TABLE_CAPTION_PROMPT = env.from_string(
    open(package_join("prompts", "markdown_table_caption.txt")).read()
)
IMAGE_CAPTION_PROMPT = env.from_string(
    open(package_join("prompts", "markdown_image_caption.txt")).read()
)

logger = get_logger(__name__)


@dataclass
class Media:
    markdown_content: str
    near_chunks: tuple[str, str]
    path: Optional[str] = None
    caption: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        assert (
            "markdown_content" in data and "near_chunks" in data
        ), f"'markdown_content' and 'near_chunks' keys are required in data dictionary but were not found. Input keys: {list(data.keys())}"
        return cls(
            markdown_content=data["markdown_content"],
            near_chunks=data["near_chunks"],
            path=data.get("path", None),
            caption=data.get("caption", None),
        )

    @property
    def size(self):
        assert self.path is not None, "Path is required to get size"
        return Image.open(self.path).size

    @abstractmethod
    def parse(self, _: Optional[LLM], image_dir: str):
        """
        Parse the markdown content to extract image path and alt text.
        Format expected: ![alt text](image.png)
        """
        match = IMAGE_PARSING_REGEX.search(self.markdown_content)
        if match is None:
            raise ValueError("No image found in the markdown content")
        image_path = match.group(1)
        if not pexists(image_path):
            image_path = pjoin(image_dir, image_path)
        assert pexists(image_path), f"image file not found: {image_path}"
        self.path = image_path

    async def parse_async(self, language_model: Optional[AsyncLLM], image_dir: str):
        self.parse(language_model, image_dir)

    def get_caption(self, vision_model: LLM):
        assert self.path is not None, "Path is required to get caption"
        if self.caption is None:
            self.caption = vision_model(
                IMAGE_CAPTION_PROMPT.render(
                    markdown_caption=self.near_chunks,
                ),
                self.path,
            )
            logger.debug(f"Caption: {self.caption}")

    async def get_caption_async(self, vision_model: AsyncLLM):
        assert self.path is not None, "Path is required to get caption"
        if self.caption is None:
            self.caption = await vision_model(
                IMAGE_CAPTION_PROMPT.render(
                    markdown_caption=self.near_chunks,
                ),
                self.path,
            )
            logger.debug(f"Caption: {self.caption}")


@dataclass
class Table(Media):
    cells: Optional[list[list[str]]] = None
    merge_area: Optional[list[tuple[int, int, int, int]]] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        assert (
            "markdown_content" in data and "near_chunks" in data
        ), f"'markdown_content' and 'near_chunks' keys are required in data dictionary but were not found. Input keys: {list(data.keys())}"
        return cls(
            markdown_content=data["markdown_content"],
            near_chunks=data["near_chunks"],
            path=data.get("path", None),
            caption=data.get("caption", None),
            cells=data.get("cells", None),
            merge_area=data.get("merge_area", None),
        )

    def parse_table(self, image_dir: str):
        html = markdown(self.markdown_content)
        cells, merges = parse_table_with_merges(html)
        self.cells = cells
        self.merge_area = merges

        if self.path is None:
            self.path = pjoin(
                image_dir,
                f"table_{hashlib.md5(str(self.cells).encode()).hexdigest()[:4]}.png",
            )
        markdown_table_to_image(self.markdown_content, self.path)

    def parse(self, table_model: Optional[LLM], image_dir: str):
        self.parse_table(image_dir)
        if table_model is None:
            return
        result = table_model(
            TABLE_PARSING_PROMPT.render(cells=self.cells, caption=self.caption),
            return_json=True,
        )
        self.merge_area = result["merge_area"]
        table = [row for row in result["table_data"]]
        if (
            all(len(row) == len(table[0]) for row in table)
            and len(table) == len(self.cells)
            and len(table[0]) == len(self.cells[0])
        ):
            self.cells = table

    async def parse_async(self, table_model: Optional[AsyncLLM], image_dir: str):
        self.parse_table(image_dir)
        if table_model is None:
            return
        result = await table_model(
            TABLE_PARSING_PROMPT.render(cells=self.cells, caption=self.caption),
            return_json=True,
        )
        self.merge_area = result["merge_area"]
        table = [row for row in result["table_data"]]
        if (
            all(len(row) == len(table[0]) for row in table)
            and len(table) == len(self.cells)
            and len(table[0]) == len(self.cells[0])
        ):
            self.cells = table

    def get_caption(self, language_model: LLM):
        if self.caption is None:
            self.caption = language_model(
                TABLE_CAPTION_PROMPT.render(
                    markdown_content=self.markdown_content,
                    markdown_caption=self.near_chunks,
                )
            )
            logger.debug(f"Caption: {self.caption}")

    async def get_caption_async(self, language_model: AsyncLLM):
        if self.caption is None:
            self.caption = await language_model(
                TABLE_CAPTION_PROMPT.render(
                    markdown_content=self.markdown_content,
                    markdown_caption=self.near_chunks,
                )
            )
            logger.debug(f"Caption: {self.caption}")


def parse_table_with_merges(
    html: str,
) -> tuple[list[list[str]], list[tuple[int, int, int, int]]]:
    """parse table in html with merge cell

    Args:
        html (str)

    Returns:
        cell_and_merge (cell: list[list[str]], merges: list[(x0: int, y0: int, x1: int, y1: int)])
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    # 计算表格最大行列
    rows = table.find_all("tr")
    max_row = 0
    col_counter = []
    for row_idx, row in enumerate(rows):
        col_span_sum = 0
        for cell in row.find_all(["td", "th"]):
            row_span = int(cell.get("rowspan", 1))
            col_span = int(cell.get("colspan", 1))
            max_row = max(max_row, row_idx + row_span)
            col_span_sum += col_span
        col_counter.append(col_span_sum)
    max_col = max(col_counter) if col_counter else 0

    # 初始化数据容器
    grid = [["" for _ in range(max_col)] for _ in range(max_row)]
    occupied = [[False for _ in range(max_col)] for _ in range(max_row)]
    merges = []

    # 主解析逻辑
    for row_idx, row in enumerate(rows):
        col_idx = 0
        for cell in row.find_all(["td", "th"]):
            # 跳过已占用的列
            while col_idx < max_col and occupied[row_idx][col_idx]:
                col_idx += 1
            if col_idx >= max_col:
                break

            # 解析单元格属性
            row_span = int(cell.get("rowspan", 1))
            col_span = int(cell.get("colspan", 1))
            cell_value = cell.get_text(strip=True)

            # 记录合并范围 (闭区间)
            x0, y0 = row_idx, col_idx
            x1 = min(row_idx + row_span - 1, max_row - 1)
            y1 = min(col_idx + col_span - 1, max_col - 1)
            if not (x0 == x1 and y0 == y1):
                merges.append((x0, y0, x1, y1))

            # 填充左上角单元格
            grid[x0][y0] = cell_value

            # 标记被合并区域
            for r in range(x0, x1 + 1):
                for c in range(y0, y1 + 1):
                    if r < max_row and c < max_col:
                        occupied[r][c] = True

            col_idx += col_span  # 移动到下一列
    return grid, merges


@dataclass
class SubSection:
    title: str
    content: str
    medias: list[Media]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        assert (
            "title" in data and "content" in data
        ), f"'title' and 'content' keys are required in data dictionary but were not found. Input keys: {list(data.keys())}"
        medias = []
        for chunk in data.get("medias", []):
            if (
                chunk.get("type", None) == "table"
                or chunk.get("cells", None) is not None
            ):
                medias.append(Table.from_dict(chunk))
            else:
                medias.append(Media.from_dict(chunk))
        return cls(
            title=data["title"],
            content=data["content"],
            medias=medias,
        )

    def iter_medias(self):
        yield from self.medias


@dataclass
class Section:
    title: str
    summary: Optional[str]
    subsections: list[SubSection]
    markdown_content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any], markdown_content: str = None):
        assert (
            "title" in data and "subsections" in data
        ), f"'title' and 'subsections' keys are required in data dictionary but were not found. Input keys: {list(data.keys())}"
        subsections = [
            SubSection.from_dict(subsection) for subsection in data["subsections"]
        ]
        assert len(subsections) != 0, "subsections is empty"
        return cls(
            title=data["title"],
            subsections=subsections,
            summary=data.get("summary", None),
            markdown_content=data.get("markdown_content", markdown_content),
        )

    def __contains__(self, key: str):
        for subsection in self.subsections:
            if subsection.title == key:
                return True
        return False

    def __getitem__(self, key: str):
        for subsection in self.subsections:
            if subsection.title == key:
                return subsection
        sim_subsec = max(self.subsections, key=lambda x: edit_distance(x.title, key))
        if edit_distance(sim_subsec.title, key) > 0.8:
            return sim_subsec
        raise KeyError(
            f"subsection not found: {key}, available subsections of {self.title} are: {[subsection.title for subsection in self.subsections]}"
        )

    def iter_medias(self):
        for subsection in self.subsections:
            yield from subsection.iter_medias()

    def validate_medias(self, image_dir: str, require_caption: bool = True):
        for media in self.iter_medias():
            if not pexists(media.path):
                basename = pbasename(media.path)
                if pexists(pjoin(image_dir, basename)):
                    media.path = pjoin(image_dir, basename)
                else:
                    raise FileNotFoundError(f"image file not found: {media.path}")
            assert (
                media.caption is not None or not require_caption
            ), f"caption is required for media: {media.path}"


def link_medias(
    medias: list[dict],
    rewritten_paragraphs: list[dict[str, Any]],
    max_chunk_size: int = 256,
) -> dict[str, Any]:
    """
    Link media elements to the most relevant paragraphs based on content proximity.

    Args:
        medias: List of media dictionaries (tables, images)
        original_paragraphs: List of original paragraph dictionaries
        rewritten_paragraphs: List of rewritten paragraph dictionaries
        max_chunk_size: Maximum size of text chunk to consider for matching

    Returns:
        The rewritten paragraphs with medias linked to appropriate sections
    """
    # Process each media element
    assert len(rewritten_paragraphs) != 0, "rewritten_paragraphs is empty"
    for media in medias:
        if len(media["near_chunks"][0]) < max_chunk_size:
            link_paragraph = rewritten_paragraphs[0]
        else:
            link_paragraph = max(
                rewritten_paragraphs,
                key=lambda x: edit_distance(
                    media["near_chunks"][0], x.get("markdown_content", "")
                ),
            )

            if "medias" not in link_paragraph:
                link_paragraph["medias"] = []
            link_paragraph["medias"].append(media)

    return rewritten_paragraphs
