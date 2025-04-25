import asyncio
from dataclasses import dataclass
from typing import Literal, Optional

from jinja2 import StrictUndefined, Template

from pptagent.llms import LLM, AsyncLLM
from pptagent.utils import get_logger, package_join, pbasename, pexists, pjoin

logger = get_logger(__name__)

LENGTHY_REWRITE_PROMPT = Template(
    open(package_join("prompts", "lengthy_rewrite.txt")).read(),
    undefined=StrictUndefined,
)


@dataclass
class Element:
    el_name: str
    content: list[str]
    description: str
    el_type: Literal["text", "image"]
    suggested_characters: int | None
    variable_length: tuple[int, int] | None
    variable_data: dict[str, list[str]] | None

    def get_schema(self):
        schema = f"Element: {self.el_name}\n"
        base_attrs = ["description", "el_type"]
        for attr in base_attrs:
            schema += f"\t{attr}: {getattr(self, attr)}\n"
        if self.el_type == "text":
            schema += f"\tsuggested_characters: {self.suggested_characters}\n"
        if self.variable_length is not None:
            schema += f"\tThe length of the element can vary between {self.variable_length[0]} and {self.variable_length[1]}\n"
        schema += f"\tThe default quantity of the element is {len(self.content)}\n"
        return schema

    @classmethod
    def from_dict(cls, el_name: str, data: dict):
        if not isinstance(data["data"], list):
            data["data"] = [data["data"]]
        if data["type"] == "text":
            suggested_characters = max(len(i) for i in data["data"])
        elif data["type"] == "image":
            suggested_characters = None
        return cls(
            el_name=el_name,
            el_type=data["type"],
            content=data["data"],
            description=data["description"],
            variable_length=data.get("variableLength", None),
            variable_data=data.get("variableData", None),
            suggested_characters=suggested_characters,
        )


@dataclass
class Layout:
    title: str
    template_id: int
    slides: list[int]
    elements: list[Element]
    vary_mapping: dict[int, int] | None  # mapping for variable elements

    @classmethod
    def from_dict(cls, title: str, data: dict):
        elements = [
            Element.from_dict(el_name, data["content_schema"][el_name])
            for el_name in data["content_schema"]
        ]
        num_vary_elements = sum((el.variable_length is not None) for el in elements)
        if num_vary_elements > 1:
            raise ValueError("Only one variable element is allowed")
        return cls(
            title=title,
            template_id=data["template_id"],
            slides=data["slides"],
            elements=elements,
            vary_mapping=data.get("vary_mapping", None),
        )

    def get_slide_id(self, data: dict):
        for el in self.elements:
            if el.variable_length is not None:
                num_vary = len(data[el.el_name]["data"])
                if num_vary < el.variable_length[0]:
                    raise ValueError(
                        f"The length of {el.el_name}: {num_vary} is less than the minimum length: {el.variable_length[0]}"
                    )
                if num_vary > el.variable_length[1]:
                    raise ValueError(
                        f"The length of {el.el_name}: {num_vary} is greater than the maximum length: {el.variable_length[1]}"
                    )
                return self.vary_mapping[str(num_vary)]
        return self.template_id

    def get_old_data(self, editor_output: Optional[dict] = None):
        if editor_output is None:
            return {el.el_name: el.content for el in self.elements}
        old_data = {}
        for el in self.elements:
            if el.variable_length is not None:
                key = str(len(editor_output[el.el_name]["data"]))
                assert (
                    key in el.variable_data
                ), f"The length of element {el.el_name} varies between {el.variable_length[0]} and {el.variable_length[1]}, but got data of length {key} which is not supported"
                old_data[el.el_name] = el.variable_data[key]
            else:
                old_data[el.el_name] = el.content
        return old_data

    def validate(self, editor_output: dict, image_dir: str):
        for el_name, el_data in editor_output.items():
            assert (
                "data" in el_data
            ), """key `data` not found in output
                    please give your output as a dict like
                    {
                        "element1": {
                            "data": ["text1", "text2"] for text elements
                            or ["/path/to/image", "..."] for image elements
                        },
                    }"""
            assert (
                el_name in self
            ), f"Element {el_name} is not a valid element, supported elements are {[el.el_name for el in self.elements]}"
            if self[el_name].el_type == "image":
                for i in range(len(el_data["data"])):
                    if pexists(pjoin(image_dir, el_data["data"][i])):
                        el_data["data"][i] = pjoin(image_dir, el_data["data"][i])
                    if not pexists(el_data["data"][i]):
                        basename = pbasename(el_data["data"][i])
                        if pexists(pjoin(image_dir, basename)):
                            el_data["data"][i] = pjoin(image_dir, basename)
                        else:
                            raise ValueError(
                                f"Image {el_data['data'][i]} not found\n"
                                "Please check the image path and use only existing images\n"
                                "Or, leave a blank list for this element"
                            )

    def validate_length(
        self, editor_output: dict, length_factor: float, language_model: LLM
    ):
        for el_name, el_data in editor_output.items():
            if self[el_name].el_type == "text":
                charater_counts = [len(i) for i in el_data["data"]]
                if (
                    max(charater_counts)
                    > self[el_name].suggested_characters * length_factor
                ):
                    el_data["data"] = language_model(
                        LENGTHY_REWRITE_PROMPT.render(
                            el_name=el_name,
                            content=el_data["data"],
                            suggested_characters=f"{self[el_name].suggested_characters} characters",
                        ),
                        return_json=True,
                    )
                    assert isinstance(
                        el_data["data"], list
                    ), f"Generated data is lengthy, expect {self[el_name].suggested_characters} characters, but got {len(el_data['data'])} characters for element {el_name}"

    async def validate_length_async(
        self, editor_output: dict, length_factor: float, language_model: AsyncLLM
    ):
        async with asyncio.TaskGroup() as tg:
            tasks = {}
            for el_name, el_data in editor_output.items():
                if self[el_name].el_type == "text":
                    charater_counts = [len(i) for i in el_data["data"]]
                    if (
                        max(charater_counts)
                        > self[el_name].suggested_characters * length_factor
                    ):
                        task = tg.create_task(
                            language_model(
                                LENGTHY_REWRITE_PROMPT.render(
                                    el_name=el_name,
                                    content=el_data["data"],
                                    suggested_characters=f"{self[el_name].suggested_characters} characters",
                                ),
                                return_json=True,
                            )
                        )
                        tasks[el_name] = task

            for el_name, task in tasks.items():
                assert isinstance(
                    editor_output[el_name]["data"], list
                ), f"Generated data is lengthy, expect {self[el_name].suggested_characters} characters, but got {len(editor_output[el_name]['data'])} characters for element {el_name}"
                new_data = await task
                logger.debug(
                    f"Lengthy rewrite for {el_name}:\n From {editor_output[el_name]['data']}\n To {new_data}"
                )
                editor_output[el_name]["data"] = new_data

    @property
    def content_schema(self):
        return "\n".join([el.get_schema() for el in self.elements])

    def remove_item(self, item: str):
        for el in self.elements:
            if item in el.content:
                el.content.remove(item)
                if len(el.content) == 0:
                    self.elements.remove(el)
                return
        else:
            raise ValueError(f"Item {item} not found in layout {self.title}")

    def __contains__(self, key: str | int):
        if isinstance(key, int):
            return key in self.slides
        elif isinstance(key, str):
            for el in self.elements:
                if el.el_name == key:
                    return True
            return False
        raise ValueError(f"Invalid key type: {type(key)}, should be str or int")

    def __getitem__(self, key: str):
        for el in self.elements:
            if el.el_name == key:
                return el
        raise ValueError(f"Element {key} not found")

    def __iter__(self):
        return iter(self.elements)

    def __len__(self):
        return len(self.elements)
