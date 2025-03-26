import tempfile
from test.conftest import test_config

import pytest
from bs4 import BeautifulSoup
from markdown import markdown

import pptagent.utils as utils
from pptagent.utils import get_json_from_response, split_markdown_to_chunks


def test_extract_json_from_markdown_block():
    """Test extracting JSON from a markdown code block."""
    response = """
    Here's the JSON you requested:

    ```json
    {
        "name": "John",
        "age": 30,
        "city": "New York"
    }
    ```

    Let me know if you need anything else.
    """

    result = get_json_from_response(response)
    assert isinstance(result, dict)
    assert result["name"] == "John"
    assert result["age"] == 30
    assert result["city"] == "New York"


def test_extract_json_from_text():
    """Test extracting JSON directly from text."""
    response = """
    Here's the JSON:

    {
        "name": "John",
        "age": 30,
        "city": "New York"
    }

    Let me know if you need anything else.
    """

    result = get_json_from_response(response)
    assert isinstance(result, dict)
    assert result["name"] == "John"
    assert result["age"] == 30
    assert result["city"] == "New York"


def test_extract_json_with_repair():
    """Test extracting JSON with minor syntax errors that can be repaired."""
    response = """
    Here's the JSON:

    {
        'name': 'John',
        'age': 30,
        'city': 'New York'
    }

    Let me know if you need anything else.
    """

    result = get_json_from_response(response)
    assert isinstance(result, dict)
    assert result["name"] == "John"
    assert result["age"] == 30
    assert result["city"] == "New York"


def test_extract_nested_json():
    """Test extracting nested JSON objects."""
    response = """
    Here's the JSON:

    {
        "person": {
            "name": "John",
            "age": 30
        },
        "address": {
            "city": "New York",
            "zip": "10001"
        }
    }
    """

    result = get_json_from_response(response)
    assert isinstance(result, dict)
    assert result["person"]["name"] == "John"
    assert result["address"]["city"] == "New York"


def test_json_not_found():
    """Test that an exception is raised when JSON is not found."""
    response = "This is just plain text with no JSON."

    with pytest.raises(Exception) as excinfo:
        get_json_from_response(response)

    assert "JSON not found" in str(excinfo.value)


def test_ppt_to_images_conversion():
    """Test converting a PPTX file to images."""
    # Run the conversion
    utils.ppt_to_images(test_config.ppt, tempfile.mkdtemp())


def test_markdown_splits():
    markdown_content = open(f"{test_config.document}/source.md").read()
    chunks = split_markdown_to_chunks(markdown_content)
    assert len(chunks) == 5
    markdown_html = markdown(markdown_content, extensions=["tables"])
    soup = BeautifulSoup(markdown_html, "html.parser")
    num_medias = len(soup.find_all("img")) + len(soup.find_all("table"))
    parsed_medias = 0
    for chunk in chunks:
        markdown_html = markdown(chunk["content"], extensions=["tables"])
        soup = BeautifulSoup(markdown_html, "html.parser")
        parsed_medias += len(soup.find_all("img")) + len(soup.find_all("table"))
    assert parsed_medias == num_medias
