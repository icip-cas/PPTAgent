from os.path import join as pjoin
from test.conftest import test_config

from pptagent.induct import SlideInducterAsync
from pptagent.model_utils import get_image_model
from pptagent.multimodal import ImageLabler
from pptagent.presentation import Presentation
from pptagent.utils import package_join


async def test_induct():
    prs = Presentation.from_file(
        package_join(test_config.template, "source.pptx"), test_config.config
    )
    labler = ImageLabler(prs, test_config.config)
    labler.apply_stats(test_config.get_image_stats())
    image_model = get_image_model("cpu")
    inducter = SlideInducterAsync(
        prs,
        pjoin(test_config.template, "slide_images"),
        pjoin(test_config.template, "template_images"),
        test_config.config,
        image_model,
        test_config.language_model,
        test_config.vision_model,
    )
    await inducter.content_induct(layout_induction=await inducter.layout_induct())
