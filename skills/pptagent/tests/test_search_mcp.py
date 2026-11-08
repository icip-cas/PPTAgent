"""The search MCP preserves provider routing and returns source links."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import httpx
from fastmcp import Client, FastMCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def load_search_mcp() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pptagent_search_mcp", ROOT / "scripts/search_mcp.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load the search MCP module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


search_mcp = load_search_mcp()


class ProviderSelectionTests(unittest.TestCase):
    def test_auto_preserves_legacy_provider_precedence_and_defaults_keyless(
        self,
    ) -> None:
        cases = (
            ({}, "parallel"),
            ({"SERPAPI_KEY": "fixture-serpapi"}, "serpapi"),
            ({"TAVILY_API_KEY": "tvly-fixture"}, "tavily"),
            (
                {
                    "SERPAPI_KEY": "fixture-serpapi",
                    "TAVILY_API_KEY": "tvly-fixture",
                },
                "serpapi",
            ),
        )
        for environment, expected in cases:
            with self.subTest(environment=sorted(environment)):
                self.assertEqual(
                    search_mcp.resolve_search_provider(environment), expected
                )

    def test_explicit_provider_requires_its_credential(self) -> None:
        with self.assertRaisesRegex(ValueError, "SERPAPI_KEY"):
            search_mcp.resolve_search_provider({"SEARCH_PROVIDER": "serpapi"})
        with self.assertRaisesRegex(ValueError, "TAVILY_API_KEY"):
            search_mcp.resolve_search_provider({"SEARCH_PROVIDER": "tavily"})

    def test_invalid_configured_tavily_key_does_not_fall_back_to_parallel(self) -> None:
        with self.assertRaisesRegex(ValueError, "beginning with 'tvly'"):
            search_mcp.resolve_search_provider({"TAVILY_API_KEY": "invalid-fixture"})

    def test_explicit_parallel_is_keyless(self) -> None:
        self.assertEqual(
            search_mcp.resolve_search_provider({"SEARCH_PROVIDER": "parallel"}),
            "parallel",
        )


class SearchMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_routes_search_and_preserves_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pptagent-search-") as directory:
            call_log = Path(directory) / "parallel-calls.jsonl"
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(Path(__file__)), "--stdio-fixture"],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PPTAGENT_SEARCH_FIXTURE_LOG": str(call_log),
                },
            )
            async with (
                stdio_client(parameters) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                self.assertTrue({"search_web", "fetch_url", "download_file"} <= names)
                self.assertNotIn("search_images", names)

                response = await session.call_tool(
                    "search_web",
                    {"query": "Parallel Search MCP source results", "max_results": 1},
                )
                self.assertFalse(response.isError)
                payload = self._payload(response)
                self.assertEqual(payload["total_results"], 1)
                self.assertEqual(payload["results"][0]["title"], "Fixture source")
                self.assertEqual(
                    payload["results"][0]["url"], "https://example.org/source"
                )
                self.assertEqual(payload["results"][0]["content"], "A useful excerpt.")
                self.assertEqual(payload["results"][0]["publish_date"], "2026-09-25")

                rejected = await session.call_tool(
                    "search_web",
                    {
                        "query": "Parallel Search MCP source results",
                        "time_range": "year",
                    },
                )
                self.assertTrue(rejected.isError)
                self.assertIn("time_range", rejected.content[0].text)

            calls = [json.loads(line) for line in call_log.read_text().splitlines()]
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                calls[0]["search_queries"], ["Parallel Search MCP source results"]
            )
            self.assertEqual(calls[0]["session_id"], "fixture-session")

    async def test_parallel_search_sends_project_user_agent(self) -> None:
        requests: list[httpx.Request] = []
        received_arguments: dict[str, Any] = {}

        def handle_request(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            message = json.loads(request.content)
            method = message["method"]
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "initialize":
                result = {
                    "protocolVersion": message["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Parallel Search Fixture", "version": "1.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "web_search",
                            "description": "Search the web.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "objective": {"type": "string"},
                                    "search_queries": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "session_id": {"type": "string"},
                                },
                                "required": [
                                    "objective",
                                    "search_queries",
                                    "session_id",
                                ],
                            },
                        }
                    ]
                }
            elif method == "tools/call":
                received_arguments.update(message["params"]["arguments"])
                result_data = {
                    "results": [
                        {
                            "title": "Fixture source",
                            "url": "https://example.org/source",
                            "excerpts": ["A useful excerpt."],
                        }
                    ]
                }
                result = {
                    "content": [{"type": "text", "text": json.dumps(result_data)}],
                    "structuredContent": result_data,
                    "isError": False,
                }
            else:
                self.fail(f"unexpected MCP request: {method}")

            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": message["id"], "result": result},
                headers={"content-type": "application/json"},
            )

        def httpx_client_factory(**kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = httpx.MockTransport(handle_request)
            return httpx.AsyncClient(**kwargs)

        transport_type = search_mcp.StreamableHttpTransport

        def transport_factory(
            url: str,
            headers: dict[str, str] | None = None,
        ) -> Any:
            return transport_type(
                url,
                headers=headers,
                httpx_client_factory=httpx_client_factory,
            )

        with patch.object(search_mcp, "StreamableHttpTransport", new=transport_factory):
            search_server = search_mcp.create_server(
                environment={},
                session_id="fixture-session",
            )
            async with Client(search_server) as caller:
                response = await caller.call_tool(
                    "search_web", {"query": "fixture query", "max_results": 1}
                )
        self.assertFalse(response.is_error)
        self.assertEqual(
            response.structured_content["results"][0]["url"],
            "https://example.org/source",
        )
        self.assertEqual(
            received_arguments,
            {
                "objective": "Find relevant web sources for: fixture query",
                "search_queries": ["fixture query"],
                "session_id": "fixture-session",
            },
        )
        self.assertGreaterEqual(len(requests), 3)
        for request in requests:
            self.assertEqual(str(request.url), search_mcp.PARALLEL_SEARCH_MCP_URL)
            self.assertEqual(
                request.headers["user-agent"], search_mcp.PARALLEL_USER_AGENT
            )
            self.assertNotIn("authorization", request.headers)

    async def test_stdio_server_keeps_configured_provider_and_does_not_fallback(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="pptagent-search-legacy-") as directory:
            parallel_marker = Path(directory) / "parallel-fallback-called"
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(Path(__file__)), "--legacy-fixture"],
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PPTAGENT_SEARCH_PARALLEL_MARKER": str(parallel_marker),
                },
            )
            async with (
                stdio_client(parameters) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                self.assertIn("search_images", {tool.name for tool in tools.tools})

                response = await session.call_tool(
                    "search_web", {"query": "configured SerpAPI source"}
                )
                self.assertFalse(response.isError)
                self.assertEqual(self._payload(response)["provider"], "serpapi")

                failed = await session.call_tool(
                    "search_web", {"query": "fixture-search-error"}
                )
                self.assertTrue(failed.isError)
                self.assertIn(
                    "configured SerpAPI fixture failure", failed.content[0].text
                )

            self.assertFalse(parallel_marker.exists())

    @staticmethod
    def _payload(response: Any) -> dict[str, Any]:
        if response.structuredContent is not None:
            return response.structuredContent
        text = next(item.text for item in response.content if item.type == "text")
        return json.loads(text)


def _stdio_fixture() -> None:
    fixture = FastMCP("Parallel Search Fixture")
    call_log = Path(os.environ["PPTAGENT_SEARCH_FIXTURE_LOG"])

    @fixture.tool()
    async def web_search(
        objective: str,
        search_queries: list[str],
        session_id: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        with call_log.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "objective": objective,
                        "search_queries": search_queries,
                        "session_id": session_id,
                        "model_name": model_name,
                    }
                )
                + "\n"
            )
        return {
            "search_id": "fixture-search",
            "results": [
                {
                    "title": "Fixture source",
                    "url": "https://example.org/source",
                    "publish_date": "2026-09-25",
                    "excerpts": ["A useful excerpt."],
                },
                {
                    "title": "Second fixture source",
                    "url": "https://example.org/second",
                    "publish_date": None,
                    "excerpts": ["Another useful excerpt."],
                },
            ],
        }

    def fixture_client(_url: str, timeout: int) -> Client:
        return Client(fixture, timeout=timeout)

    search_mcp.create_server(
        {"SEARCH_PROVIDER": "auto"},
        parallel_client_factory=fixture_client,
        session_id="fixture-session",
    ).run(show_banner=False)


def _legacy_stdio_fixture() -> None:
    legacy_server = FastMCP("Legacy Search Fixture")
    legacy_module = ModuleType("deeppresenter.tools.search")

    @legacy_server.tool()
    async def search_web(
        query: str,
        max_results: int = 3,
        time_range: str | None = None,
    ) -> dict[str, Any]:
        if query == "fixture-search-error":
            raise RuntimeError("configured SerpAPI fixture failure")
        return {"query": query, "provider": "serpapi"}

    @legacy_server.tool()
    async def search_images(query: str) -> dict[str, Any]:
        return {"query": query, "provider": "serpapi"}

    class FixturePlaywrightConverter:
        @staticmethod
        async def shutdown() -> None:
            return None

    legacy_module.search_web = search_web
    legacy_module.search_images = search_images
    legacy_module.PlaywrightConverter = FixturePlaywrightConverter
    sys.modules["deeppresenter.tools.search"] = legacy_module

    def unexpected_parallel_client(_url: str, timeout: int) -> Client:
        marker = Path(os.environ["PPTAGENT_SEARCH_PARALLEL_MARKER"])
        marker.write_text("unexpected fallback")
        raise AssertionError("configured provider failure must not fall back")

    search_mcp.create_server(
        {
            "SEARCH_PROVIDER": "auto",
            "SERPAPI_KEY": "fixture-serpapi",
            "TAVILY_API_KEY": "tvly-fixture",
        },
        parallel_client_factory=unexpected_parallel_client,
    ).run(show_banner=False)


if __name__ == "__main__":
    if sys.argv[1:] == ["--stdio-fixture"]:
        _stdio_fixture()
    elif sys.argv[1:] == ["--legacy-fixture"]:
        _legacy_stdio_fixture()
    else:
        unittest.main()
