from os.path import join as pjoin
from pathlib import Path
from test.conftest import test_config

import pytest

from pptagent.induct import SlideInducter, SlideInducterAsync
from pptagent.multimodal import ImageLabler
from pptagent.presentation import Presentation
from pptagent.utils import package_join

CUTOFF = 8


def prepare_slides(prs: Presentation):
    slides = []
    slide_image_folder = pjoin(test_config.template, "slide_images")
    template_image_folder = pjoin(test_config.template, "template_images")
    for i, sld in enumerate(prs.slides):
        if i < CUTOFF:
            slides.append(sld)
        else:
            Path(pjoin(slide_image_folder, f"slide_{i:04d}.jpg")).unlink(
                missing_ok=True
            )
            Path(pjoin(template_image_folder, f"slide_{i:04d}.jpg")).unlink(
                missing_ok=True
            )
    prs.slides = slides
    return prs


@pytest.mark.llm
def test_layout_induct():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    prs = prepare_slides(prs)

    inducter = SlideInducter(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model.to_sync(),
        test_config.vision_model.to_sync(),
    )
    inducter.layout_induct()


@pytest.mark.asyncio
@pytest.mark.llm
async def test_layout_induct_async():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    prs = prepare_slides(prs)

    inducter = SlideInducterAsync(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model,
        test_config.vision_model,
    )
    inducter.prs.slides = inducter.prs.slides[:8]
    for i, sld in enumerate(inducter.prs.slides):
        sld.slide_idx = i + 1
    await inducter.layout_induct()


@pytest.mark.llm
def test_content_induct():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    prs = prepare_slides(prs)

    inducter = SlideInducter(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model.to_sync(),
        test_config.vision_model.to_sync(),
    )
    layout_induction = {}
    for layout_name, cluster in test_config.get_slide_induction().items():
        cluster.pop("content_schema")
        layout_induction[layout_name] = cluster
        break

    inducter.content_induct(layout_induction=layout_induction)


@pytest.mark.asyncio
@pytest.mark.llm
async def test_content_induct_async():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    prs = prepare_slides(prs)

    inducter = SlideInducterAsync(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        test_config.image_model,
        test_config.language_model,
        test_config.vision_model,
    )
    layout_induction = {}
    for layout_name, cluster in test_config.get_slide_induction().items():
        cluster.pop("content_schema")
        layout_induction[layout_name] = cluster
        break
    await inducter.content_induct(layout_induction=layout_induction)
