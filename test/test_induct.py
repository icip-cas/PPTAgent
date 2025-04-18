from os.path import join as pjoin
from test.conftest import test_config

import pytest

from pptagent.induct import SlideInducter, SlideInducterAsync
from pptagent.multimodal import ImageLabler
from pptagent.presentation import Presentation
from pptagent.utils import package_join


@pytest.mark.llm
def test_induct():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    inducter = SlideInducter(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model.to_sync(),
        test_config.vision_model.to_sync(),
    )
    inducter.content_induct(layout_induction=inducter.layout_induct())


@pytest.mark.asyncio
@pytest.mark.llm
async def test_induct_async():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    inducter = SlideInducterAsync(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model,
        test_config.vision_model,
    )
    await inducter.content_induct(layout_induction=await inducter.layout_induct())
