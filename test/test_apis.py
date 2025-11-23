import pytest
from bs4 import BeautifulSoup
from pptagent_pptx import Presentation

from pptagent.apis import (
    API_TYPES,
    CodeExecutor,
    SlideEditError,
    markdown,
    process_element,
    replace_para,
)
from test.conftest import test_config


def test_api_docs():
    executor = CodeExecutor(3)
    docs = executor.get_apis_docs(API_TYPES.Agent.value)
    assert len(docs) > 0


def test_parse_action_allows_only_literals_and_names():
    executor = CodeExecutor(1)
    func, args, kwargs = executor._parse_action_call(
        "replace_paragraph(1, 2, 'text', style='plain')"
    )

    assert func == "replace_paragraph"
    assert args == [1, 2, "text"]
    assert kwargs == {"style": "plain"}


def test_parse_action_rejects_attribute_and_calls():
    executor = CodeExecutor(1)

    with pytest.raises(SlideEditError):
        executor._parse_action_call("os.system('ls')")


def test_parse_action_rejects_non_literal_arguments():
    executor = CodeExecutor(1)

    with pytest.raises(SlideEditError):
        executor._parse_action_call("replace_paragraph(1, [x for x in range(2)], 'a')")


def test_replace_para():
    text = "这是一个**加粗和*斜体*文本**，还有*斜体和`Code def a+b`*，~~删除~~，[链接](http://example.com)"
    prs = Presentation(test_config.ppt)
    slide = prs.slides[0]
    replace_para(0, text, slide.shapes[0])
    runs = slide.shapes[0].text_frame.paragraphs[0].runs
    assert runs[1].font.bold
    assert runs[2].font.bold and runs[2].font.italic
    assert runs[6].font.name == "Consolas"
    assert runs[8].font.strikethrough
    assert runs[10].hyperlink.address == "http://example.com"


def test_list_parsing():
    text = """
    - 项目1
    - 项目2

    1. 项目1
    2. 项目2
    """
    html = markdown(text).strip()
    soup = BeautifulSoup(html, "html.parser")
    blocks = process_element(soup)
    assert len(blocks) == 1
    assert "ol" not in html and "ul" not in html
