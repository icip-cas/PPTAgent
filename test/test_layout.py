from test.conftest import test_config

from pptagent.presentation import Layout


def test_layout():
    template = test_config.get_slide_induction()
    for k, v in template.items():
        if k == "functional_keys":
            continue
        layout = Layout.from_dict(k, v)
        layout.content_schema
        layout.get_old_data()
