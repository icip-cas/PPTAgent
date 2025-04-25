import asyncio
import json
import traceback
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pptagent.agent import Agent
from pptagent.apis import API_TYPES, CodeExecutor
from pptagent.document import Document, OutlineItem, get_outlines_overview
from pptagent.llms import LLM, AsyncLLM
from pptagent.presentation import Layout, Picture, Presentation, SlidePage, StyleArg
from pptagent.utils import Config, edit_distance, get_logger, tenacity_decorator

logger = get_logger(__name__)

style = StyleArg.all_true()
style.area = False


class FunctionalLayouts(Enum):
    OPENING = "Opening"
    TOC = "Table of Contents"
    SECTION_OUTLINE = "Section Outline"
    ENDING = "Ending"


@dataclass
class PPTGen(ABC):
    """
    Stage II: Presentation Generation
    An abstract base class for generating PowerPoint presentations.
    It accepts a reference presentation as input, then generates a presentation outline and slides.
    """

    roles = []
    text_embedder: LLM | AsyncLLM
    language_model: LLM | AsyncLLM
    vision_model: LLM | AsyncLLM
    retry_times: int = 3
    force_pages: bool = False
    error_exit: bool = False
    record_cost: bool = False
    length_factor: float | None = None
    _initialized: bool = False

    def __post_init__(self):
        self._initialized = False
        self._hire_staffs(self.record_cost, self.language_model, self.vision_model)
        assert (
            self.length_factor is None or self.length_factor > 0
        ), "length_factor must be positive or None"

    def set_reference(
        self,
        config: Config,
        slide_induction: dict,
        presentation: Presentation,
        hide_small_pic_ratio: Optional[float] = 0.2,
        keep_in_background: bool = True,
    ):
        """
        Set the reference presentation and extracted presentation information.

        Args:
            presentation (Presentation): The presentation object.
            slide_induction (dict): The slide induction data.

        Returns:
            PPTGen: The updated PPTGen object.
        """
        self.config = config
        self.presentation = presentation
        self.functional_keys = slide_induction.pop("functional_keys")
        self.content_keys = [
            k for k in slide_induction if k not in self.functional_keys
        ]
        self.layouts = {k: Layout.from_dict(k, v) for k, v in slide_induction.items()}
        self.empty_prs = deepcopy(self.presentation)
        assert (
            hide_small_pic_ratio is None or hide_small_pic_ratio > 0
        ), "hide_small_pic_ratio must be positive or None"
        if hide_small_pic_ratio is not None:
            self._hide_small_pics(hide_small_pic_ratio, keep_in_background)
        self._initialized = True
        return self

    def generate_pres(
        self,
        source_doc: Document,
        num_slides: Optional[int] = None,
        outline: Optional[list[OutlineItem]] = None,
    ):
        """
        Generate a PowerPoint presentation.

        Args:
            source_doc (Document): The source document.
            num_slides (Optional[int]): The number of slides to generate.
            outline (Optional[List[OutlineItem]]): The outline of the presentation.

        Returns:
            dict: A dictionary containing the presentation data and history.

        Raise:
            ValueError: if failed to generate presentation outline.
        """
        assert self._initialized, "PPTGen not initialized, call `set_reference` first"
        self.source_doc = source_doc
        succ_flag = True
        if outline is None:
            self.outline = self.generate_outline(num_slides, source_doc)
        else:
            self.outline = outline
        self.simple_outline = get_outlines_overview(self.outline)
        generated_slides = []
        code_executors = []
        for slide_idx, outline_item in enumerate(self.outline):
            if self.force_pages and slide_idx == num_slides:
                break
            try:
                slide, code_executor = self.generate_slide(slide_idx, outline_item)
                generated_slides.append(slide)
                code_executors.append(code_executor)
            except Exception as e:
                logger.warning(
                    "Failed to generate slide, error_exit=%s, error: %s",
                    self.error_exit,
                    str(e),
                )
                traceback.print_exc()
                if self.error_exit:
                    succ_flag = False
                    break

        # Collect history data
        history = self._collect_history(
            sum(code_executors, start=CodeExecutor(self.retry_times))
        )

        if succ_flag:
            self.empty_prs.slides = generated_slides
            prs = self.empty_prs
        else:
            prs = None

        self.empty_prs = deepcopy(self.presentation)
        return prs, history

    def generate_outline(
        self,
        num_slides: int,
        source_doc: Document,
    ):
        """
        Generate an outline for the presentation.

        Args:
            num_slides (int): The number of slides to generate.

        Returns:
            dict: The generated outline.
        """
        assert self._initialized, "PPTGen not initialized, call `set_reference` first"
        turn_id, outline = self.staffs["planner"](
            num_slides=num_slides,
            document_overview=source_doc.get_overview(),
        )
        if num_slides == 1 and isinstance(outline, dict):
            outline = [outline]
        outline = self._fix_outline(outline, source_doc, turn_id)
        return self._add_functional_layouts(outline)

    @abstractmethod
    def generate_slide(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Generate a slide from the outline item.
        """
        raise NotImplementedError("Subclass must implement this method")

    @abstractmethod
    def interact(
        self,
        target_slide: SlidePage,
        slide_idx: int,
        outline_item: OutlineItem,
        source_doc: Document,
        query: str,
    ) -> tuple[SlidePage, CodeExecutor]:
        raise NotImplementedError("Subclass must implement this method")

    def _add_functional_layouts(self, outline: list[OutlineItem]):
        """
        Add functional layouts to the outline.
        """
        fixed_functional_slides = [
            (FunctionalLayouts.TOC.value, 0),  # toc should be added before opening
            (FunctionalLayouts.OPENING.value, 0),
            (FunctionalLayouts.ENDING.value, 999999),  # append to the end
        ]
        for title, pos in fixed_functional_slides:
            layout = max(self.functional_keys, key=lambda x: edit_distance(x, title))
            if edit_distance(layout, title) > 0.7:
                outline.insert(pos, OutlineItem(title, "Functional", {}))

        section_outline = max(
            self.functional_keys,
            key=lambda x: edit_distance(x, FunctionalLayouts.SECTION_OUTLINE.value),
        )
        if (
            not edit_distance(section_outline, FunctionalLayouts.SECTION_OUTLINE.value)
            > 0.7
        ):
            return outline
        pre_section = None
        for item in deepcopy(outline):
            if item.section == "Functional":
                continue
            if item.section != pre_section:
                new_item = OutlineItem(
                    f"Section Outline of {item.section}", "Functional", {}
                )
                outline.insert(outline.index(item), new_item)
            if item.section != pre_section:
                pre_section = item.section
        return outline

    def _hide_small_pics(self, area_ratio: float, keep_in_background: bool):
        for layout in self.layouts.values():
            template_slide = self.presentation.slides[layout.template_id - 1]
            pictures = list(template_slide.shape_filter(Picture, return_father=True))
            if len(pictures) == 0:
                continue
            for father, pic in pictures:
                if pic.area / pic.slide_area < area_ratio:
                    if keep_in_background:
                        father.shapes.remove(pic)
                    else:
                        father.shapes.remove(pic)
                        father.backgrounds.append(pic)
                    layout.remove_item(pic.caption.strip())

            if len(list(template_slide.shape_filter(Picture))) == 0:
                logger.debug(
                    "All pictures in layout %s are too small, set to pure text layout",
                    layout.title,
                )
                layout.title = layout.title.replace(":image", ":text")
                layout.elements = [el for el in layout.elements if el.el_type == "text"]

    def _fix_outline(
        self, outline: list[dict], source_doc: Document, turn_id: int, retry: int = 0
    ) -> list[OutlineItem]:
        """
        Validate the generated outline.

        Raises:
            ValueError: If the outline is invalid.
        """
        try:
            outline_items = [
                OutlineItem.from_dict(outline_item) for outline_item in outline
            ]
            for outline_item in outline_items:
                source_doc.retrieve(outline_item.indexs)
            return outline_items
        except Exception as e:
            retry += 1
            logger.info(
                "Failed to generate outline, tried %d/%d times, error: %s",
                retry,
                self.retry_times,
                str(e),
            )
            logger.debug(traceback.format_exc())
            if retry < self.retry_times:
                new_outline = self.staffs["planner"].retry(
                    str(e), traceback.format_exc(), turn_id, retry
                )
                return self._fix_outline(new_outline, source_doc, turn_id, retry)
            else:
                raise ValueError("Failed to generate outline, tried too many times")

    def _collect_history(self, code_executor: CodeExecutor):
        """
        Collect the history of code execution, API calls and agent steps.

        Returns:
            dict: The collected history data.
        """
        history = {
            "agents": {},
            "code_history": code_executor.code_history,
            "api_history": code_executor.api_history,
        }

        for role_name, role in self.staffs.items():
            history["agents"][role_name] = role.history
            role._history = []

        return history

    def _hire_staffs(
        self,
        record_cost: bool,
        language_model: LLM | AsyncLLM,
        vision_model: LLM | AsyncLLM,
    ) -> dict[str, Agent]:
        """
        Initialize agent roles and their models
        """
        llm_mapping = {
            "language": language_model,
            "vision": vision_model,
        }
        self.staffs = {
            role: Agent(
                role,
                record_cost=record_cost,
                text_model=self.text_embedder,
                llm_mapping=llm_mapping,
            )
            for role in ["planner"] + self.roles
        }


@dataclass
class PPTGenAsync(PPTGen):
    """
    Asynchronous base class for generating PowerPoint presentations.
    Extends PPTGen with async functionality.
    """

    def __post_init__(self):
        super().__post_init__()
        for k in list(self.staffs.keys()):
            self.staffs[k] = self.staffs[k].to_async()

    async def generate_pres(
        self,
        source_doc: Document,
        num_slides: Optional[int] = None,
        outline: Optional[list[OutlineItem]] = None,
    ):
        """
        Asynchronously generate a PowerPoint presentation.
        """
        assert (
            self._initialized
        ), "AsyncPPTAgent not initialized, call `set_reference` first"
        self.source_doc = source_doc
        succ_flag = True
        if outline is None:
            self.outline = await self.generate_outline(num_slides, source_doc)
        else:
            self.outline = outline
        self.simple_outline = get_outlines_overview(self.outline)

        slide_tasks = []
        for slide_idx, outline_item in enumerate(self.outline):
            if self.force_pages and slide_idx == num_slides:
                break
            slide_tasks.append(self.generate_slide(slide_idx, outline_item))

        slide_results = await asyncio.gather(*slide_tasks, return_exceptions=True)

        generated_slides = []
        code_executors = []
        for result in slide_results:
            if isinstance(result, Exception):
                if self.error_exit:
                    succ_flag = False
                    break
                continue
            if result is not None:
                slide, code_executor = result
                generated_slides.append(slide)
                code_executors.append(code_executor)

        history = self._collect_history(
            sum(code_executors, start=CodeExecutor(self.retry_times))
        )

        if succ_flag:
            self.empty_prs.slides = generated_slides
            prs = self.empty_prs
        else:
            prs = None

        self.empty_prs = deepcopy(self.presentation)
        return prs, history

    async def generate_outline(
        self,
        num_slides: int,
        source_doc: Document,
    ):
        """
        Asynchronously generate an outline for the presentation.
        """
        assert (
            self._initialized
        ), "AsyncPPTAgent not initialized, call `set_reference` first"

        turn_id, outline = await self.staffs["planner"](
            num_slides=num_slides,
            document_overview=source_doc.get_overview(),
        )
        if num_slides == 1 and isinstance(outline, dict):
            outline = [outline]
        outline = await self._fix_outline(outline, source_doc, turn_id)
        return self._add_functional_layouts(outline)

    @abstractmethod
    async def generate_slide(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously generate a slide from the outline item.
        """
        raise NotImplementedError("Subclass must implement this method")

    @abstractmethod
    async def interact(
        self,
        target_slide: SlidePage,
        slide_idx: int,
        outline_item: OutlineItem,
        source_doc: Document,
        query: str,
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously interact with the user on a specific slide.
        """
        raise NotImplementedError("Subclass must implement this method")

    async def _fix_outline(
        self, outline: list[dict], source_doc: Document, turn_id: int, retry: int = 0
    ) -> list[OutlineItem]:
        """
        Asynchronously validate the generated outline.
        """
        try:
            outline_items = [
                OutlineItem.from_dict(outline_item) for outline_item in outline
            ]
            for outline_item in outline_items:
                source_doc.retrieve(outline_item.indexs)
            return outline_items
        except Exception as e:
            retry += 1
            logger.info(
                "Failed to generate outline, tried %d/%d times, error: %s",
                retry,
                self.retry_times,
                str(e),
            )
            logger.debug(traceback.format_exc())
            if retry < self.retry_times:
                new_outline = await self.staffs["planner"].retry(
                    str(e), traceback.format_exc(), turn_id, retry
                )
                return await self._fix_outline(new_outline, source_doc, turn_id, retry)
            else:
                raise ValueError("Failed to generate outline, tried too many times")


class PPTAgent(PPTGen):
    """
    A class to generate PowerPoint presentations with a crew of agents.
    """

    roles: list[str] = [
        "editor",
        "coder",
        "copilot",
        "content_organizer",
        "layout_selector",
    ]

    def generate_slide(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Generate a slide from the outline item.
        """
        layout, header, slide_content = self._select_layout(slide_idx, outline_item)
        command_list, template_id = self._generate_content(
            layout, slide_content, header
        )
        slide, code_executor = self._edit_slide(command_list, template_id)
        return slide, code_executor

    def interact(
        self,
        target_slide: SlidePage,
        slide_idx: int,
        outline_item: OutlineItem,
        source_doc: Document,
        query: str,
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Interact with the user on a specific slide.
        """
        self.source_doc = source_doc
        for layout in self.layouts.values():
            if (
                target_slide.slide_idx in layout.slides
            ):  # this slide_idx is the index of the slide in the original presentation, instead of the index of the slide in the outline
                break
        else:
            raise ValueError(f"Slide {target_slide.slide_idx} not found in any layout")
        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        if len(content_source) == 0:
            key_points = []
        else:
            _, key_points = self.staffs["content_organizer"](
                content_source=content_source
            )
        slide_content = json.dumps(key_points, indent=2, ensure_ascii=False)
        if len(images) > 0 and target_slide.get_content_type() == "image":
            slide_content += "\nImages:\n" + "\n".join(images)
        turn_id, copilot_output = self.staffs["copilot"](
            query=query,
            retr_chunks=slide_content,
            schema=layout.content_schema,
            slide_content=target_slide.to_html(),
        )
        command_list, template_id = self._generate_commands(
            copilot_output, layout, turn_id
        )
        return self._edit_slide(command_list, template_id)

    @tenacity_decorator
    def _select_layout(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[Layout, str, str]:
        """
        Select a layout for the slide.
        """
        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        if len(content_source) == 0:
            key_points = []
        else:
            _, key_points = self.staffs["content_organizer"](
                content_source=content_source
            )
        slide_content = json.dumps(key_points, indent=2, ensure_ascii=False)
        if len(images) > 0:
            slide_content += "\nImages:\n" + "\n".join(images)

        _, layout_selection = self.staffs["layout_selector"](
            outline=self.simple_outline,
            slide_description=header,
            slide_content=slide_content,
            available_layouts=self.content_keys,
        )
        layout = max(
            self.layouts.keys(),
            key=lambda x: edit_distance(x, layout_selection["layout"]),
        )
        if "image" in layout and len(images) == 0:
            logger.debug(
                f"An image layout: {layout} is selected, but no images are provided, please check the parsed document and outline item:\n {outline_item}"
            )
        elif "image" not in layout and len(images) > 0:
            logger.debug(
                f"A pure text layout: {layout} is selected, but images are provided, please check the parsed document and outline item:\n {outline_item}\n Set images to empty list."
            )
            slide_content = slide_content[: slide_content.rfind("\nImages:\n")]
        return self.layouts[layout], header, slide_content

    def _generate_content(
        self,
        layout: Layout,
        slide_content: str,
        slide_description: str,
    ) -> tuple[list, int]:
        """
        Synergize Agents to generate a slide.

        Args:
            layout (Layout): The layout data.
            slide_content (str): The slide content.
            slide_description (str): The description of the slide.

        Returns:
            tuple[list, int]: The generated command list and template id.
        """
        turn_id, editor_output = self.staffs["editor"](
            outline=self.simple_outline,
            metadata=self.source_doc.metainfo,
            slide_description=slide_description,
            slide_content=slide_content,
            schema=layout.content_schema,
        )
        command_list, template_id = self._generate_commands(
            editor_output, layout, turn_id
        )
        return command_list, template_id

    def _edit_slide(
        self, command_list: list, template_id: int
    ) -> tuple[SlidePage, CodeExecutor]:
        code_executor = CodeExecutor(self.retry_times)
        turn_id, edit_actions = self.staffs["coder"](
            api_docs=code_executor.get_apis_docs(API_TYPES.Agent.value),
            edit_target=self.presentation.slides[template_id - 1].to_html(),
            command_list="\n".join([str(i) for i in command_list]),
        )
        for error_idx in range(self.retry_times):
            edit_slide: SlidePage = deepcopy(self.presentation.slides[template_id - 1])
            feedback = code_executor.execute_actions(
                edit_actions, edit_slide, self.source_doc
            )
            if feedback is None:
                break
            logger.info(
                "Failed to generate slide, tried %d/%d times, error: %s",
                error_idx + 1,
                self.retry_times,
                str(feedback[1]),
            )
            logger.debug(traceback.format_exc())
            if error_idx == self.retry_times:
                raise Exception(
                    f"Failed to generate slide, tried too many times at editing\ntraceback: {feedback[1]}"
                )
            edit_actions = self.staffs["coder"].retry(
                feedback[0], feedback[1], turn_id, error_idx + 1
            )
        self.empty_prs.build_slide(edit_slide)
        return edit_slide, code_executor

    def _generate_commands(
        self, editor_output: dict, layout: Layout, turn_id: int, retry: int = 0
    ):
        """
        Generate commands for editing the slide content.
        """
        command_list = []
        try:
            layout.validate(editor_output, self.source_doc.image_dir)
            if self.length_factor is not None:
                layout.validate_length(
                    editor_output, self.length_factor, self.language_model
                )
            old_data = layout.get_old_data(editor_output)
            template_id = layout.get_slide_id(editor_output)
        except Exception as e:
            if retry < self.retry_times:
                new_output = self.staffs["editor"].retry(
                    e,
                    traceback.format_exc(),
                    turn_id,
                    retry + 1,
                )
                return self._generate_commands(new_output, layout, turn_id, retry + 1)
            else:
                raise Exception(
                    f"Failed to generate commands, tried too many times at editing\ntraceback: {e}"
                )

        for el_name, old_content in old_data.items():
            if not isinstance(old_content, list):
                old_content = [old_content]

            new_content = editor_output.get(el_name, {"data": []})["data"]
            if not isinstance(new_content, list):
                new_content = [new_content]
            new_content = [i for i in new_content if i]
            quantity_change = len(new_content) - len(old_content)
            command_list.append(
                (
                    el_name,
                    layout[el_name].el_type,
                    f"quantity_change: {quantity_change}",
                    old_content,
                    new_content,
                )
            )

        assert len(command_list) > 0, "No commands generated"
        return command_list, template_id


class PPTAgentAsync(PPTGenAsync):
    """
    Asynchronous version of PPTAgent that uses AsyncAgent for concurrent processing.
    """

    roles: list[str] = [
        "editor",
        "coder",
        "copilot",
        "content_organizer",
        "layout_selector",
    ]

    async def generate_slide(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously generate a slide from the outline item.
        """
        try:
            if outline_item.section == "Functional":
                layout = self.layouts[
                    max(
                        self.functional_keys,
                        key=lambda x: edit_distance(x, outline_item.purpose),
                    )
                ]

                header, _, _ = outline_item.retrieve(slide_idx, self.source_doc)
                if outline_item.purpose == FunctionalLayouts.SECTION_OUTLINE.value:
                    slide_content = (
                        "Overview of the Document:\n"
                        + self.source_doc.get_overview(include_summary=True)
                    )
                else:
                    slide_content = ""
            else:
                layout, header, slide_content = await self._select_layout(
                    slide_idx, outline_item
                )
            command_list, template_id = await self._generate_content(
                layout, slide_content, header
            )
            slide, code_executor = await self._edit_slide(command_list, template_id)
        except Exception as e:
            logger.error(f"Failed to generate slide {slide_idx}, error: {e}")
            traceback.print_exc()
            raise e
        return slide, code_executor

    async def interact(
        self,
        target_slide: SlidePage,
        slide_idx: int,
        outline_item: OutlineItem,
        source_doc: Document,
        query: str,
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously interact with the user on a specific slide.
        """
        self.source_doc = source_doc
        for layout in self.layouts.values():
            if target_slide.slide_idx in layout.slides:
                break
        else:
            raise ValueError(f"Slide {target_slide.slide_idx} not found in any layout")

        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        if len(content_source) == 0:
            key_points = []
        else:
            _, key_points = await self.staffs["content_organizer"](
                content_source=content_source
            )
        slide_content = json.dumps(key_points, indent=2, ensure_ascii=False)
        if len(images) > 0 and target_slide.get_content_type() == "image":
            slide_content += "\nImages:\n" + "\n".join(images)

        turn_id, copilot_output = await self.staffs["copilot"](
            query=query,
            retr_chunks=slide_content,
            schema=layout.content_schema,
            slide_content=target_slide.to_html(),
        )
        command_list, template_id = await self._generate_commands(
            copilot_output, layout, turn_id
        )
        return await self._edit_slide(command_list, template_id)

    @tenacity_decorator
    async def _select_layout(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[Layout, str, str]:
        """
        Asynchronously select a layout for the slide.
        """
        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        if len(content_source) == 0:
            key_points = []
        else:
            _, key_points = await self.staffs["content_organizer"](
                content_source=content_source
            )
        slide_content = json.dumps(key_points, indent=2, ensure_ascii=False)
        if len(images) > 0:
            slide_content += "\nImages:\n" + "\n".join(images)

        _, layout_selection = await self.staffs["layout_selector"](
            outline=self.simple_outline,
            slide_description=header,
            slide_content=slide_content,
            available_layouts=self.content_keys,
        )
        layout = max(
            self.layouts.keys(),
            key=lambda x: edit_distance(x, layout_selection["layout"]),
        )
        if "image" in layout and len(images) == 0:
            logger.debug(
                f"An image layout: {layout} is selected, but no images are provided, please check the parsed document and outline item:\n {outline_item}"
            )
        elif "image" not in layout and len(images) > 0:
            logger.debug(
                f"A pure text layout: {layout} is selected, but images are provided, please check the parsed document and outline item:\n {outline_item}\n Set images to empty list."
            )
            slide_content = slide_content[: slide_content.rfind("\nImages:\n")]
        return self.layouts[layout], header, slide_content

    async def _generate_content(
        self,
        layout: Layout,
        slide_content: str,
        slide_description: str,
    ) -> tuple[list, int]:
        """
        Asynchronously generate content for the slide.
        """
        turn_id, editor_output = await self.staffs["editor"](
            outline=self.simple_outline,
            slide_description=slide_description,
            metadata=self.source_doc.metainfo,
            slide_content=slide_content,
            schema=layout.content_schema,
        )
        command_list, template_id = await self._generate_commands(
            editor_output, layout, turn_id
        )
        return command_list, template_id

    async def _edit_slide(
        self, command_list: list, template_id: int
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously edit the slide.
        """
        code_executor = CodeExecutor(self.retry_times)
        turn_id, edit_actions = await self.staffs["coder"](
            api_docs=code_executor.get_apis_docs(API_TYPES.Agent.value),
            edit_target=self.presentation.slides[template_id - 1].to_html(),
            command_list="\n".join([str(i) for i in command_list]),
        )

        for error_idx in range(self.retry_times):
            edit_slide: SlidePage = deepcopy(self.presentation.slides[template_id - 1])
            feedback = code_executor.execute_actions(
                edit_actions, edit_slide, self.source_doc
            )
            if feedback is None:
                break
            logger.info(
                "Failed to generate slide, tried %d/%d times, error: %s",
                error_idx + 1,
                self.retry_times,
                str(feedback[1]),
            )
            if error_idx == self.retry_times:
                raise Exception(
                    f"Failed to generate slide, tried too many times at editing\ntraceback: {feedback[1]}"
                )
            edit_actions = await self.staffs["coder"].retry(
                feedback[0], feedback[1], turn_id, error_idx + 1
            )
        self.empty_prs.build_slide(edit_slide)
        return edit_slide, code_executor

    async def _generate_commands(
        self, editor_output: dict, layout: Layout, turn_id: int, retry: int = 0
    ):
        """
        Asynchronously generate commands for editing the slide content.

        Args:
            editor_output (dict): The editor output.
            layout (Layout): The layout object containing content schema.
            turn_id (int): The turn ID for retrying.
            retry (int, optional): The number of retries. Defaults to 0.

        Returns:
            list: A list of commands.

        Raises:
            Exception: If command generation fails.
        """
        command_list = []
        try:
            layout.validate(editor_output, self.source_doc.image_dir)
            if self.length_factor is not None:
                await layout.validate_length_async(
                    editor_output, self.length_factor, self.language_model
                )
            old_data = layout.get_old_data(editor_output)
            template_id = layout.get_slide_id(editor_output)
        except Exception as e:
            if retry < self.retry_times:
                new_output = await self.staffs["editor"].retry(
                    e,
                    traceback.format_exc(),
                    turn_id,
                    retry + 1,
                )
                return await self._generate_commands(
                    new_output, layout, turn_id, retry + 1
                )
            else:
                raise Exception(
                    f"Failed to generate commands, tried too many times at editing\ntraceback: {e}"
                )

        for el_name, old_content in old_data.items():
            if not isinstance(old_content, list):
                old_content = [old_content]

            new_content = editor_output.get(el_name, {"data": []})["data"]
            if not isinstance(new_content, list):
                new_content = [new_content]
            new_content = [i for i in new_content if i]
            quantity_change = len(new_content) - len(old_content)
            command_list.append(
                (
                    el_name,
                    layout[el_name].el_type,
                    f"quantity_change: {quantity_change}",
                    old_content,
                    new_content,
                )
            )

        assert len(command_list) > 0, "No commands generated"
        return command_list, template_id
