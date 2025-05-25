from os.path import isfile
from os.path import join as pjoin
from test.conftest import test_config

import pytest

from pptagent.model_utils import parse_pdf, prs_dedup
from pptagent.presentation import Presentation


@pytest.mark.llm
def test_prs_dedup():
    prs = Presentation.from_file(
        pjoin(test_config.template, "source.pptx"), test_config.config
    )
    prs.slides = [prs.slides[0]] * 2
    prs = prs_dedup(prs, test_config.text_model.to_sync())
    assert len(prs) == 1


@pytest.mark.llm
def test_parse_pdf():
    parse_pdf(
        pjoin(test_config.template, "source.pdf"),
        pjoin(test_config.template, "pdf_out"),
    )
    assert isfile(pjoin(test_config.template, "pdf_out", "source.md"))
