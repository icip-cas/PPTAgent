import tempfile
from os.path import join as pjoin
from test.conftest import test_config

from pptagent.induct import SlideInducterAsync
from pptagent.model_utils import get_image_model
from pptagent.presentation import Presentation


async def test_induct():
    prs = Presentation.from_file(test_config.template, test_config.config)
    image_model = get_image_model("cpu")
    with tempfile.TemporaryDirectory() as tmp_dir:
        inducter = SlideInducterAsync(
            prs,
            pjoin(tmp_dir, "slide_images"),
            pjoin(tmp_dir, "template_images"),
            test_config.config,
            image_model,
            test_config.language_model,
            test_config.vision_model,
        )
        layout_induction = await inducter.layout_induct()
        content_induction = await inducter.content_induct(layout_induction)
        print(content_induction)
