from dataclasses import asdict, dataclass
from typing import Literal, Optional

from pptagent.utils import pbasename, pexists, pjoin


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
        schema = asdict(self)
        schema.pop("content")
        schema.pop("variable_data")
        if self.el_type == "image":
            schema.pop("suggested_characters")
        if self.variable_length is None:
            schema.pop("variable_length")
        else:
            schema["variableLength"] = "The length of the element should be between "
            schema[
                "variableLength"
            ] += f"{self.variable_length[0]} and {self.variable_length[1]}"
        schema["type"] = schema.pop("el_type")
        schema["defaultQuantitity"] = len(self.content)
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

    def validate(
        self, editor_output: dict, length_factor: float | None, image_dir: str
    ):
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
            if length_factor is not None:
                charater_counts = [len(i) for i in el_data["data"]]
                if (
                    max(charater_counts)
                    > self[el_name].suggested_characters * length_factor
                ):
                    raise ValueError(
                        f"Content for '{el_name}' exceeds character limit ({max(charater_counts)} > {self[el_name].suggested_characters}). "
                        f"Please reduce the content length to maintain slide readability and visual balance. "
                        f"Current text: '{el_data['data']}'"
                    )
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

    @property
    def content_schema(self):
        return {el.el_name: el.get_schema() for el in self.elements}

    @property
    def overview(self):
        overview = f"Layout: {self.title}\n"
        for el in self.elements:
            overview += f"{el.el_name}: {el.el_type}\n"
            if el.variable_length is not None:
                overview += f"variable length: {el.variable_length[0]} - {el.variable_length[1]}\n"
            else:
                overview += f"element length: {len(el.content)}\n"
            overview += f"description: {el.description}\n"
            if el.el_type == "text":
                overview += f"suggested characters: {el.suggested_characters}\n"
            overview += "\n"
        return overview

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
