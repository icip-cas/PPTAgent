from test.conftest import test_config

import pytest


@pytest.mark.asyncio
@pytest.mark.llm
async def test_asyncllm():
    """
    Test the async LLM connection and functionality.
    """
    # Test connection
    result = await test_config.language_model.test_connection()
    assert result is True, "Async LLM connection failed"

    # Test response generation
    response = await test_config.language_model("Hello, how are you?", max_tokens=1)
    assert response is not None, "Async LLM returned None response"
    assert len(response) > 0, "Async LLM returned empty response"


@pytest.mark.llm
def test_sync_llm():
    """
    Test the synchronous LLM connection and functionality.
    """

    sync_language_model = test_config.language_model.to_sync()
    result = sync_language_model.test_connection()
    assert result is True, "Sync LLM connection failed"
    response = sync_language_model("Hello, how are you?", max_tokens=1)
    assert response is not None, "Sync LLM returned None response"
    assert len(response) > 0, "Sync LLM returned empty response"
