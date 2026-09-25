#!/usr/bin/env python3
"""Expose the skill's web and image search tools as one stdio MCP server."""

import importlib
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from types import ModuleType
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

SearchProvider = Literal["parallel", "serpapi", "tavily"]
ParallelClientFactory = Callable[..., Client]
PARALLEL_SEARCH_MCP_URL = "https://search.parallel.ai/mcp"
# Keep PPTAgent in the outbound User-Agent for aggregate MCP attribution.
PARALLEL_USER_AGENT = f"PPTAgent python-httpx/{httpx.__version__}"


def _parallel_client(url: str, timeout: float) -> Client:
    transport = StreamableHttpTransport(
        url, headers={"User-Agent": PARALLEL_USER_AGENT}
    )
    return Client(transport, timeout=timeout)


def _keys(value: str) -> tuple[str, ...]:
    return tuple(key.strip() for key in value.split(",") if key.strip())


def _tavily_keys(environment: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        key
        for key in _keys(environment.get("TAVILY_API_KEY", ""))
        if key.startswith("tvly")
    )


def _configured_legacy_provider(
    environment: Mapping[str, str],
) -> Literal["serpapi", "tavily"] | None:
    if _keys(environment.get("SERPAPI_KEY", "")):
        return "serpapi"
    if _tavily_keys(environment):
        return "tavily"
    return None


def resolve_search_provider(environment: Mapping[str, str]) -> SearchProvider:
    requested = environment.get("SEARCH_PROVIDER", "auto").strip().lower() or "auto"
    if requested not in {"auto", "parallel", "serpapi", "tavily"}:
        raise ValueError("SEARCH_PROVIDER must be auto, parallel, serpapi, or tavily")

    serpapi_keys = _keys(environment.get("SERPAPI_KEY", ""))
    tavily_key_value = environment.get("TAVILY_API_KEY", "")
    tavily_keys = _tavily_keys(environment)

    if requested == "auto":
        if serpapi_keys:
            return "serpapi"
        if tavily_key_value.strip() and not tavily_keys:
            raise ValueError("TAVILY_API_KEY must contain a key beginning with 'tvly'")
        if tavily_keys:
            return "tavily"
        return "parallel"

    if requested == "serpapi" and not serpapi_keys:
        raise ValueError("SERPAPI_KEY is required when SEARCH_PROVIDER=serpapi")
    if requested == "tavily" and not tavily_keys:
        raise ValueError(
            "a valid TAVILY_API_KEY is required when SEARCH_PROVIDER=tavily"
        )
    return requested


def _parallel_payload(response: Any) -> dict[str, Any]:
    payload = response.structured_content
    if payload is None:
        payload = response.data
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    if isinstance(payload, dict):
        return payload

    text_blocks = [item.text for item in response.content if item.type == "text"]
    if len(text_blocks) != 1:
        raise ToolError("Parallel Search MCP returned an invalid response")
    try:
        payload = json.loads(text_blocks[0])
    except json.JSONDecodeError as error:
        raise ToolError("Parallel Search MCP returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise ToolError("Parallel Search MCP returned an invalid response")
    return payload


def _normalize_results(
    query: str,
    payload: Mapping[str, Any],
    max_results: int,
) -> dict[str, Any]:
    raw_results = payload.get("results")
    if not isinstance(raw_results, list):
        raise ToolError("Parallel Search MCP response is missing results")

    results: list[dict[str, Any]] = []
    for item in raw_results[:max_results]:
        if not isinstance(item, dict):
            raise ToolError("Parallel Search MCP returned an invalid result")
        title = item.get("title")
        url = item.get("url")
        excerpts = item.get("excerpts", [])
        parsed_url = urlsplit(url) if isinstance(url, str) else None
        if (
            not isinstance(title, str)
            or not title.strip()
            or parsed_url is None
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
            or not isinstance(excerpts, list)
            or any(not isinstance(excerpt, str) for excerpt in excerpts)
        ):
            raise ToolError("Parallel Search MCP returned an invalid source")

        result = {
            "title": title,
            "url": url,
            "displayed_link": parsed_url.netloc,
            "content": "\n\n".join(excerpts),
        }
        publish_date = item.get("publish_date")
        if publish_date is not None:
            if not isinstance(publish_date, str):
                raise ToolError("Parallel Search MCP returned an invalid publish date")
            result["publish_date"] = publish_date
        results.append(result)

    return {"query": query, "total_results": len(results), "results": results}


def create_server(
    environment: Mapping[str, str] | None = None,
    parallel_client_factory: ParallelClientFactory | None = None,
    session_id: str | None = None,
) -> FastMCP:
    active_environment = environment if environment is not None else os.environ
    provider = resolve_search_provider(active_environment)
    client_factory = parallel_client_factory or _parallel_client
    search_session_id = session_id or uuid4().hex
    legacy_module: ModuleType | None = None

    def load_legacy_module() -> ModuleType:
        nonlocal legacy_module
        if legacy_module is None:
            legacy_module = importlib.import_module("deeppresenter.tools.search")
        return legacy_module

    @asynccontextmanager
    async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {}
        finally:
            if legacy_module is not None:
                await legacy_module.PlaywrightConverter.shutdown()

    server = FastMCP("Search", lifespan=lifespan)

    @server.tool()
    async def search_web(
        query: str,
        max_results: int = 3,
        time_range: Literal["month", "year"] | None = None,
    ) -> dict[str, Any]:
        """Search for web sources through the selected provider."""
        if not query.strip():
            raise ToolError("query must not be empty")
        if max_results < 1:
            raise ToolError("max_results must be positive")

        if provider == "parallel":
            if time_range is not None:
                raise ToolError(
                    "Parallel Search MCP does not support time_range; select SerpAPI or Tavily."
                )
            async with client_factory(PARALLEL_SEARCH_MCP_URL, timeout=60) as client:
                response = await client.call_tool(
                    "web_search",
                    {
                        "objective": f"Find relevant web sources for: {query}",
                        "search_queries": [query],
                        "session_id": search_session_id,
                    },
                    timeout=60,
                )
            return _normalize_results(query, _parallel_payload(response), max_results)

        legacy_tool = getattr(load_legacy_module(), "search_web", None)
        if legacy_tool is None:
            raise ToolError(f"The selected {provider} search tool is unavailable")
        return await legacy_tool.fn(query, max_results, time_range)

    if _configured_legacy_provider(active_environment) is not None:

        @server.tool()
        async def search_images(query: str) -> dict[str, Any]:
            """Search for web images through the configured legacy provider."""
            legacy_tool = getattr(load_legacy_module(), "search_images", None)
            if legacy_tool is None:
                raise ToolError("The configured image search tool is unavailable")
            return await legacy_tool.fn(query)

    @server.tool()
    async def fetch_url(url: str, body_only: bool = True) -> str:
        """Fetch and extract the main text from a web page."""
        return await load_legacy_module().fetch_url.fn(url, body_only)

    @server.tool()
    async def download_file(url: str, output_file: str) -> str:
        """Download a file inside the current working directory."""
        return await load_legacy_module().download_file.fn(url, output_file)

    return server


def main() -> None:
    create_server().run(show_banner=False)


if __name__ == "__main__":
    main()
