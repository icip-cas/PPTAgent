import json

import httpx
import pytest

from deeppresenter.utils.config import (
    LLM,
    MINIMAX_DEFAULT_IMAGE_MODEL,
    MINIMAX_IMAGE_ENDPOINTS,
    MINIMAX_IMAGE_PATH,
    Endpoint,
)

IMAGE_URL = "https://example.com/generated.png"


def _transport(body: dict, status_code: int = 200, requests: list | None = None):
    """Build a mock transport that records requests and replays a fixed body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handler)


def _url_response(urls: list[str] | None = None) -> dict:
    return {
        "id": "trace-id",
        "data": {"image_urls": urls if urls is not None else [IMAGE_URL]},
        "metadata": {"success_count": "1", "failed_count": "0"},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


def _endpoint(requests: list, body: dict | None = None, **kwargs) -> Endpoint:
    kwargs.setdefault("model", MINIMAX_DEFAULT_IMAGE_MODEL)
    kwargs.setdefault("api_key", "test-key")
    return Endpoint(
        provider="minimax",
        client_kwargs={
            "transport": _transport(body or _url_response(), requests=requests)
        },
        **kwargs,
    )


def test_native_provider_skips_openai_client():
    endpoint = Endpoint(provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL)
    assert endpoint._client is None


def test_regional_endpoints_are_resolved():
    for region, url in MINIMAX_IMAGE_ENDPOINTS.items():
        endpoint = Endpoint(
            provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL, region=region
        )
        assert endpoint._minimax_image_url() == url
        assert url.endswith(MINIMAX_IMAGE_PATH)


def test_default_region_is_used_without_region():
    endpoint = Endpoint(provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL)
    assert endpoint._minimax_image_url() == MINIMAX_IMAGE_ENDPOINTS["global_en"]


def test_unknown_region_is_rejected():
    endpoint = Endpoint(
        provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL, region="nowhere"
    )
    with pytest.raises(AssertionError):
        endpoint._minimax_image_url()


def test_base_url_overrides_region():
    endpoint = Endpoint(
        provider="minimax",
        model=MINIMAX_DEFAULT_IMAGE_MODEL,
        region="cn_zh",
        base_url="https://gateway.example.com/",
    )
    assert (
        endpoint._minimax_image_url()
        == f"https://gateway.example.com{MINIMAX_IMAGE_PATH}"
    )


def test_base_url_with_operation_path_is_not_duplicated():
    endpoint = Endpoint(
        provider="minimax",
        model=MINIMAX_DEFAULT_IMAGE_MODEL,
        base_url=f"https://gateway.example.com{MINIMAX_IMAGE_PATH}",
    )
    assert (
        endpoint._minimax_image_url()
        == f"https://gateway.example.com{MINIMAX_IMAGE_PATH}"
    )


async def test_request_mapping_and_authorization():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests)

    await endpoint._generate_image_minimax(
        prompt="a red bicycle", width=1280, height=720, timeout=30
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == MINIMAX_IMAGE_ENDPOINTS["global_en"]
    assert request.headers["Authorization"] == "Bearer test-key"
    payload = json.loads(request.content)
    assert payload["model"] == MINIMAX_DEFAULT_IMAGE_MODEL
    assert payload["prompt"] == "a red bicycle"
    assert payload["width"] == 1280
    assert payload["height"] == 720
    assert payload["response_format"] == "url"


async def test_image_urls_are_parsed():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests)

    response = await endpoint._generate_image_minimax(
        prompt="a lighthouse", width=1024, height=1024, timeout=30
    )

    assert len(response.data) == 1
    assert response.data[0].url == IMAGE_URL


async def test_base64_response_format_is_parsed():
    requests: list[httpx.Request] = []
    body = {
        "data": {"image_base64": ["QUJD"]},
        "metadata": {"success_count": "1", "failed_count": "0"},
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }
    endpoint = _endpoint(
        requests, body=body, sampling_parameters={"response_format": "base64"}
    )

    response = await endpoint._generate_image_minimax(
        prompt="a canyon", width=1024, height=1024, timeout=30
    )

    assert json.loads(requests[0].content)["response_format"] == "base64"
    assert response.data[0].b64_json == "QUJD"


async def test_unknown_response_format_is_rejected():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests, sampling_parameters={"response_format": "tiff"})

    with pytest.raises(AssertionError):
        await endpoint._generate_image_minimax(
            prompt="a canyon", width=1024, height=1024, timeout=30
        )
    assert requests == []


async def test_extra_sampling_parameters_are_forwarded():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(
        requests, sampling_parameters={"prompt_optimizer": True, "seed": 7, "n": 2}
    )

    await endpoint._generate_image_minimax(
        prompt="a forest", width=1024, height=1024, timeout=30
    )

    payload = json.loads(requests[0].content)
    assert payload["prompt_optimizer"] is True
    assert payload["seed"] == 7
    assert payload["n"] == 2


async def test_aspect_ratio_replaces_explicit_size():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests, sampling_parameters={"aspect_ratio": "16:9"})

    await endpoint._generate_image_minimax(
        prompt="a skyline", width=1280, height=720, timeout=30
    )

    payload = json.loads(requests[0].content)
    assert payload["aspect_ratio"] == "16:9"
    assert "width" not in payload
    assert "height" not in payload


async def test_default_model_is_used_for_blank_model():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests, model="")

    await endpoint._generate_image_minimax(
        prompt="a desert", width=1024, height=1024, timeout=30
    )

    assert json.loads(requests[0].content)["model"] == MINIMAX_DEFAULT_IMAGE_MODEL


async def test_out_of_range_size_is_rejected():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests)

    with pytest.raises(AssertionError):
        await endpoint._generate_image_minimax(
            prompt="a tiny icon", width=256, height=256, timeout=30
        )
    assert requests == []


async def test_error_status_code_is_raised():
    requests: list[httpx.Request] = []
    body = {
        "data": {},
        "metadata": {"success_count": "0", "failed_count": "1"},
        "base_resp": {"status_code": 1026, "status_msg": "sensitive content"},
    }
    endpoint = _endpoint(requests, body=body)

    with pytest.raises(AssertionError, match="1026"):
        await endpoint._generate_image_minimax(
            prompt="a prompt", width=1024, height=1024, timeout=30
        )


async def test_empty_image_list_is_rejected():
    requests: list[httpx.Request] = []
    endpoint = _endpoint(requests, body=_url_response([]))

    with pytest.raises(AssertionError):
        await endpoint._generate_image_minimax(
            prompt="a prompt", width=1024, height=1024, timeout=30
        )


async def test_chat_call_is_not_supported():
    endpoint = Endpoint(provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL)
    with pytest.raises(NotImplementedError):
        await endpoint.call(
            messages=[{"role": "user", "content": "hi"}], soft_response_parsing=False
        )


async def test_llm_generate_image_routes_to_native_provider():
    requests: list[httpx.Request] = []
    llm = LLM(
        provider="minimax",
        region="cn_zh",
        model=MINIMAX_DEFAULT_IMAGE_MODEL,
        api_key="test-key",
        client_kwargs={"transport": _transport(_url_response(), requests=requests)},
    )

    response = await llm.generate_image(
        prompt="a mountain", width=1280, height=720, retry_times=1
    )

    assert response.data[0].url == IMAGE_URL
    assert str(requests[0].url) == MINIMAX_IMAGE_ENDPOINTS["cn_zh"]


async def test_llm_validate_accepts_native_provider():
    llm = LLM(provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL, api_key="test-key")
    await llm.validate()


async def test_llm_validate_requires_api_key():
    llm = LLM(provider="minimax", model=MINIMAX_DEFAULT_IMAGE_MODEL)
    with pytest.raises(AssertionError):
        await llm.validate()
