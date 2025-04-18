import tempfile
from copy import deepcopy
from test.conftest import test_config

from pptagent.presentation import Presentation
from pptagent.utils import Config


def test_presentation():
    presentation = Presentation.from_file(test_config.ppt, Config(tempfile.mkdtemp()))
    assert len(presentation.slides) == 1
    for sld in presentation.slides:
        sld.to_html(show_image=False)
    deepcopy(presentation)
    presentation.save("test.pptx", layout_only=True)
