from test.conftest import test_config

from pptagent.document import Document, OutlineItem, Table


async def test_document_async():
    with open(f"{test_config.document}/source.md") as f:
        markdown_content = f.read()
    image_dir = test_config.document
    doc = await Document.from_markdown_async(
        markdown_content,
        test_config.language_model,
        test_config.vision_model,
        image_dir,
    )
    assert len(list(doc.iter_medias())) == 3
    assert sum(isinstance(media, Table) for media in doc.iter_medias()) == 1


def test_document_from_dict():
    document = Document.from_dict(
        test_config.get_document_json(),
        test_config.document,
        True,
    )
    document.overview
    document.metainfo
    document.retrieve({"Building effective agents": ["What are agents?"]})
    medias = list(document.iter_medias())
    assert len(medias) == 10
    assert sum(isinstance(media, Table) for media in medias) == 6


def test_outline_retrieve():
    document = Document.from_dict(
        test_config.get_document_json(),
        test_config.document,
        False,
    )
    outline = test_config.get_outline()
    for outline_item in outline:
        item = OutlineItem(**outline_item)
        print(item.retrieve(0, document))
