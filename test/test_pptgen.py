from test.conftest import test_config

import pytest

from pptagent.document import Document, OutlineItem
from pptagent.pptgen import PPTAgent, PPTAgentAsync
from pptagent.presentation import Presentation
from pptagent.utils import pjoin


@pytest.mark.llm
def test_outline_generation():
    document = Document.from_dict(
        test_config.get_document_json(), test_config.document, False
    )
    pptgen = PPTAgent(
        test_config.text_model.to_sync(),
        test_config.language_model.to_sync(),
        test_config.vision_model.to_sync(),
    ).set_reference(
        config=test_config.config,
        presentation=Presentation.from_file(
            pjoin(test_config.template, "source.pptx"), test_config.config
        ),
        slide_induction=test_config.get_slide_induction(),
    )
    pptgen.generate_outline(3, document)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_outline_generation_async():
    document = Document.from_dict(
        test_config.get_document_json(), test_config.document, False
    )
    pptgen = PPTAgentAsync(
        test_config.text_model,
        test_config.language_model,
        test_config.vision_model,
    ).set_reference(
        config=test_config.config,
        presentation=Presentation.from_file(
            pjoin(test_config.template, "source.pptx"), test_config.config
        ),
        slide_induction=test_config.get_slide_induction(),
    )
    await pptgen.generate_outline(3, document)


@pytest.mark.llm
def test_pptgen():
    pptgen = PPTAgent(
        test_config.text_model.to_sync(),
        language_model=test_config.language_model.to_sync(),
        vision_model=test_config.vision_model.to_sync(),
    ).set_reference(
        config=test_config.config,
        presentation=Presentation.from_file(
            pjoin(test_config.template, "source.pptx"), test_config.config
        ),
        slide_induction=test_config.get_slide_induction(),
    )
    document = Document.from_dict(
        test_config.get_document_json(), test_config.document, False
    )
    outline = test_config.get_outline()
    outline = [OutlineItem.from_dict(outline[2])]
    pptgen.generate_pres(document, outline=outline)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_pptgen_async():
    pptgen = PPTAgentAsync(
        test_config.text_model,
        language_model=test_config.language_model,
        vision_model=test_config.vision_model,
    ).set_reference(
        config=test_config.config,
        presentation=Presentation.from_file(
            pjoin(test_config.template, "source.pptx"), test_config.config
        ),
        slide_induction=test_config.get_slide_induction(),
    )

    document = Document.from_dict(
        test_config.get_document_json(), test_config.document, False
    )
    outline = test_config.get_outline()
    outline = [OutlineItem.from_dict(outline[2])]
    await pptgen.generate_pres(document, outline=outline)
