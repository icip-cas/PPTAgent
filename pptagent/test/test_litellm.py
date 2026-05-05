import sys
import types
from unittest import mock

import pytest


def _install_litellm_stub():
    """Install a fake litellm module so tests run without the real package."""
    fake = types.ModuleType("litellm")
    fake.completion = mock.MagicMock(name="litellm.completion")
    fake.acompletion = mock.AsyncMock(name="litellm.acompletion")
    fake.image_generation = mock.MagicMock(name="litellm.image_generation")
    fake.aimage_generation = mock.AsyncMock(name="litellm.aimage_generation")
    sys.modules["litellm"] = fake
    return fake


@pytest.fixture(autouse=True)
def litellm_stub():
    fake = _install_litellm_stub()
    yield fake
    sys.modules.pop("litellm", None)


def _make_completion_response(content: str = "Hello!"):
    from types import SimpleNamespace

    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_litellm_llm_calls_completion(litellm_stub):
    litellm_stub.completion.return_value = _make_completion_response("test reply")

    from pptagent.litellm import LiteLLMLLM

    llm = LiteLLMLLM(model="anthropic/claude-haiku-4-5", api_key="sk-test")
    result = llm("Hello")

    litellm_stub.completion.assert_called_once()
    call_kwargs = litellm_stub.completion.call_args
    assert call_kwargs.kwargs["model"] == "anthropic/claude-haiku-4-5"
    assert call_kwargs.kwargs["api_key"] == "sk-test"
    assert call_kwargs.kwargs["drop_params"] is True
    assert result == "test reply"


def test_litellm_llm_omits_blank_credentials(litellm_stub):
    litellm_stub.completion.return_value = _make_completion_response()

    from pptagent.litellm import LiteLLMLLM

    llm = LiteLLMLLM(model="openai/gpt-4o")
    llm("Hi")

    call_kwargs = litellm_stub.completion.call_args.kwargs
    assert "api_key" not in call_kwargs
    assert "api_base" not in call_kwargs


def test_litellm_llm_forwards_base_url(litellm_stub):
    litellm_stub.completion.return_value = _make_completion_response()

    from pptagent.litellm import LiteLLMLLM

    llm = LiteLLMLLM(
        model="custom/model", base_url="http://localhost:8000", api_key="key"
    )
    llm("Hi")

    call_kwargs = litellm_stub.completion.call_args.kwargs
    assert call_kwargs["api_base"] == "http://localhost:8000"


@pytest.mark.asyncio
async def test_async_litellm_llm_calls_acompletion(litellm_stub):
    litellm_stub.acompletion.return_value = _make_completion_response("async reply")

    from pptagent.litellm import AsyncLiteLLMLLM

    llm = AsyncLiteLLMLLM(model="anthropic/claude-haiku-4-5", api_key="sk-test")
    result = await llm("Hello")

    litellm_stub.acompletion.assert_called_once()
    call_kwargs = litellm_stub.acompletion.call_args.kwargs
    assert call_kwargs["drop_params"] is True
    assert result == "async reply"


def test_litellm_llm_to_async(litellm_stub):
    from pptagent.litellm import AsyncLiteLLMLLM, LiteLLMLLM

    llm = LiteLLMLLM(model="anthropic/claude-haiku-4-5", api_key="sk-test")
    async_llm = llm.to_async()
    assert isinstance(async_llm, AsyncLiteLLMLLM)
    assert async_llm.model == "anthropic/claude-haiku-4-5"
    assert async_llm.api_key == "sk-test"


def test_async_litellm_llm_to_sync(litellm_stub):
    from pptagent.litellm import AsyncLiteLLMLLM, LiteLLMLLM

    llm = AsyncLiteLLMLLM(model="gemini/gemini-2.0-flash", api_key="key")
    sync_llm = llm.to_sync()
    assert isinstance(sync_llm, LiteLLMLLM)
    assert sync_llm.model == "gemini/gemini-2.0-flash"
