from test.conftest import test_config

import pytest

from pptagent.document import Document, OutlineItem


@pytest.mark.llm
def test_document():
    with open(f"{test_config.document}/source.md") as f:
        markdown_content = f.read()
    cutoff = markdown_content.find("## When (and when not) to use agents")
    image_dir = test_config.document
    doc = Document.from_markdown(
        markdown_content[:cutoff],
        test_config.language_model.to_sync(),
        test_config.vision_model.to_sync(),
        image_dir,
    )
    doc.get_overview(include_summary=True)
    doc.metainfo


@pytest.mark.asyncio
@pytest.mark.llm
async def test_document_async():
    with open(f"{test_config.document}/source.md") as f:
        markdown_content = f.read()
    cutoff = markdown_content.find("## When (and when not) to use agents")
    image_dir = test_config.document
    await Document.from_markdown_async(
        markdown_content[:cutoff],
        test_config.language_model,
        test_config.vision_model,
        image_dir,
    )


def test_document_from_dict():
    document = Document.from_dict(
        test_config.get_document_json(),
        test_config.document,
        True,
    )
    document.get_overview(include_summary=True)
    document.metainfo
    document.retrieve({"Building effective agents": ["What are agents?"]})


def test_outline_retrieve():
    document = Document.from_dict(
        test_config.get_document_json(),
        test_config.document,
        False,
    )
    outline = test_config.get_outline()
    for outline_item in outline:
        item = OutlineItem.from_dict(outline_item)
        print(item.retrieve(0, document))
