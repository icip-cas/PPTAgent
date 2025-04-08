import asyncio
import json
import traceback
from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Optional

from pptagent.agent import Agent, AsyncAgent
from pptagent.apis import API_TYPES, CodeExecutor
from pptagent.document import Document, OutlineItem
from pptagent.layout import Layout
from pptagent.llms import LLM, AsyncLLM
from pptagent.presentation import Presentation, SlidePage, StyleArg
from pptagent.utils import Config, edit_distance, get_logger

logger = get_logger(__name__)

style = StyleArg.all_true()
style.area = False


@dataclass
class PPTGen(ABC):
    """
    Stage II: Presentation Generation
    An abstract base class for generating PowerPoint presentations.
    It accepts a reference presentation as input, then generates a presentation outline and slides.
    """

    roles: list[str] = field(default_factory=list)

    def __init__(
        self,
        text_embedder: LLM | AsyncLLM,
        language_model: LLM | AsyncLLM,
        vision_model: LLM | AsyncLLM,
        retry_times: int = 3,
        force_pages: bool = False,
        error_exit: bool = False,
        record_cost: bool = True,
        length_factor: float | None = None,
    ):
        """
        Initialize the PPTGen.

        Args:
            text_model (LLM): The text model for generating content.
            retry_times (int): The number of times to retry failed actions.
            force_pages (bool): Whether to force a specific number of pages.
            error_exit (bool): Whether to exit on error.
            record_cost (bool): Whether to record the cost of generation.
            **kwargs: Additional arguments.
        """
        self.text_embedder = text_embedder
        self.retry_times = retry_times
        self.force_pages = force_pages
        self.error_exit = error_exit
        self.length_factor = length_factor
        self._hire_staffs(record_cost, language_model, vision_model)
        self._initialized = False

    def set_reference(
        self,
        config: Config,
        slide_induction: dict,
        presentation: Presentation,
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
        self.layouts = {k: Layout.from_dict(k, v) for k, v in slide_induction.items()}
        self.empty_prs = deepcopy(self.presentation)
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
        self.simple_outline = "\n".join(
            [
                f"Slide {slide_idx+1}: {item.purpose}"
                for slide_idx, item in enumerate(self.outline)
            ]
        )
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
            document_overview=source_doc.overview,
            functional_layouts=self.functional_keys,
        )
        outline = self._valid_outline(outline, source_doc, turn_id)
        return outline

    def _valid_outline(
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
            logger.info(
                "Failed to generate outline, tried %d/%d times, error: %s",
                retry,
                self.retry_times,
                str(e),
            )
            if retry < self.retry_times:
                new_outline = self.staffs["planner"].retry(
                    str(e), traceback.format_exc(), turn_id, retry + 1
                )
                return self._valid_outline(new_outline, source_doc, turn_id, retry + 1)
            else:
                raise ValueError("Failed to generate outline, tried too many times")

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
        _, copilot_output = self.staffs["copilot"](
            query=query,
            retr_chunks=slide_content,
            schema=layout.content_schema,
            slide_content=target_slide.to_html(),
        )
        command_list, template_id = self._generate_commands(copilot_output, layout)
        return self._edit_slide(command_list, template_id)

    def _select_layout(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[Layout, str, str]:
        """
        Generate a slide from the outline item.
        """
        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        available_layouts = "\n".join(
            [layout.overview for layout in self.layouts.values()]
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
            available_layouts=available_layouts,
            functional_layouts=self.functional_keys,
        )
        layout = max(
            self.layouts.keys(),
            key=lambda x: edit_distance(x, layout_selection["layout"]),
        )
        if "image" in layout and len(images) == 0:
            logger.info(
                f"An image layout: {layout} is selected, but no images are provided, please check the parsed document and outline item:\n {outline_item}"
            )
        elif "image" not in layout and len(images) > 0:
            logger.info(
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
        _, editor_output = self.staffs["editor"](
            outline=self.simple_outline,
            slide_description=slide_description,
            metadata=self.source_doc.metainfo,
            slide_content=slide_content,
            schema=layout.content_schema,
        )
        command_list, template_id = self._generate_commands(editor_output, layout)
        return command_list, template_id

    def _edit_slide(
        self, command_list: list, template_id: int
    ) -> tuple[SlidePage, CodeExecutor]:
        code_executor = CodeExecutor(self.retry_times)
        coder_turn_id, edit_actions = self.staffs["coder"](
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
                str(feedback),
            )
            if error_idx == self.retry_times:
                raise Exception(
                    f"Failed to generate slide, tried too many times at editing\ntraceback: {feedback[1]}"
                )
            edit_actions = self.staffs["coder"].retry(
                feedback[0], feedback[1], coder_turn_id, error_idx + 1
            )
        self.empty_prs.build_slide(edit_slide)
        return edit_slide, code_executor

    def _generate_commands(self, editor_output: dict, layout: Layout, retry: int = 0):
        """
        Generate commands for editing the slide content.

        Args:
            editor_output (dict): The editor output.
            layout (Layout): The layout object containing content schema.
            retry (int, optional): The number of retries. Defaults to 0.

        Returns:
            list: A list of commands.

        Raises:
            Exception: If command generation fails.
        """
        command_list = []
        try:
            layout.validate(
                editor_output, self.length_factor, self.source_doc.image_dir
            )
            old_data = layout.get_old_data(editor_output)
            template_id = layout.get_slide_id(editor_output)
        except Exception as e:
            if retry < self.retry_times:
                new_output = self.staffs["editor"].retry(
                    e,
                    traceback.format_exc(),
                    retry + 1,
                )
                return self._generate_commands(new_output, layout, retry + 1)
            elif retry > self.retry_times:
                logger.error("Buggy condition, retry times > max_retry_times")
                raise Exception(
                    f"Failed to generate commands, retry times ({retry}) > max_retry_times ({self.retry_times}), may be a bug"
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
                    layout.content_schema[el_name]["type"],
                    f"quantity_change: {quantity_change}",
                    old_content,
                    new_content,
                )
            )

        assert len(command_list) > 0, "No commands generated"
        return command_list, template_id


@dataclass
class PPTGenAsync(PPTGen):
    """
    Asynchronous base class for generating PowerPoint presentations.
    Extends PPTGen with async functionality.
    """

    def _hire_staffs(
        self,
        record_cost: bool,
        language_model: AsyncLLM,
        vision_model: AsyncLLM,
    ) -> dict[str, AsyncAgent]:
        """
        Initialize async agent roles and their models
        """
        llm_mapping = {
            "language": language_model,
            "vision": vision_model,
        }
        self.staffs = {
            role: AsyncAgent(
                role,
                record_cost=record_cost,
                text_model=self.text_embedder,
                llm_mapping=llm_mapping,
            )
            for role in ["planner"] + self.roles
        }

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
        self.simple_outline = "\n".join(
            [
                f"Slide {slide_idx+1}: {item.purpose}"
                for slide_idx, item in enumerate(self.outline)
            ]
        )

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
                logger.warning(
                    "Failed to generate slide, error_exit=%s, error: %s",
                    self.error_exit,
                    str(result),
                )
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
            document_overview=source_doc.overview,
            functional_layouts=self.functional_keys,
        )
        outline = await self._valid_outline(outline, source_doc, turn_id)
        return outline

    async def _valid_outline(
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
            logger.info(
                "Failed to generate outline, tried %d/%d times, error: %s",
                retry,
                self.retry_times,
                str(e),
            )
            if retry < self.retry_times:
                new_outline = await self.staffs["planner"].retry(
                    str(e), traceback.format_exc(), turn_id, retry + 1
                )
                return await self._valid_outline(
                    new_outline, source_doc, turn_id, retry + 1
                )
            else:
                raise ValueError("Failed to generate outline, tried too many times")

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
        layout, header, slide_content = await self._select_layout(
            slide_idx, outline_item
        )
        command_list, template_id = await self._generate_content(
            layout, slide_content, header
        )
        slide, code_executor = await self._edit_slide(command_list, template_id)
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

        _, copilot_output = await self.staffs["copilot"](
            query=query,
            retr_chunks=slide_content,
            schema=layout.content_schema,
            slide_content=target_slide.to_html(),
        )
        command_list, template_id = await self._generate_commands(
            copilot_output, layout, 0
        )
        return await self._edit_slide(command_list, template_id)

    async def _select_layout(
        self, slide_idx: int, outline_item: OutlineItem
    ) -> tuple[Layout, str, str]:
        """
        Asynchronously select a layout for the slide.
        """
        header, content_source, images = outline_item.retrieve(
            slide_idx, self.source_doc
        )
        available_layouts = "\n".join(
            [layout.overview for layout in self.layouts.values()]
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
            available_layouts=available_layouts,
            functional_layouts=self.functional_keys,
        )
        layout = max(
            self.layouts.keys(),
            key=lambda x: edit_distance(x, layout_selection["layout"]),
        )
        if "image" in layout and len(images) == 0:
            logger.info(
                f"An image layout is selected, but no images are provided, please check the parsed document and outline item:\n {outline_item}"
            )
        elif "image" not in layout and len(images) > 0:
            logger.info(
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
        editor_turn_id, editor_output = await self.staffs["editor"](
            outline=self.simple_outline,
            slide_description=slide_description,
            metadata=self.source_doc.metainfo,
            slide_content=slide_content,
            schema=layout.content_schema,
        )
        command_list, template_id = await self._generate_commands(
            editor_output, layout, editor_turn_id
        )
        return command_list, template_id

    async def _edit_slide(
        self, command_list: list, template_id: int
    ) -> tuple[SlidePage, CodeExecutor]:
        """
        Asynchronously edit the slide.
        """
        code_executor = CodeExecutor(self.retry_times)
        coder_turn_id, edit_actions = await self.staffs["coder"](
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
                str(feedback),
            )
            if error_idx == self.retry_times:
                raise Exception(
                    f"Failed to generate slide, tried too many times at editing\ntraceback: {feedback[1]}"
                )
            edit_actions = await self.staffs["coder"].retry(
                feedback[0], feedback[1], coder_turn_id, error_idx + 1
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
            layout.validate(
                editor_output, self.length_factor, self.source_doc.image_dir
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
                    layout.content_schema[el_name]["type"],
                    f"quantity_change: {quantity_change}",
                    old_content,
                    new_content,
                )
            )

        assert len(command_list) > 0, "No commands generated"
        return command_list, template_id
