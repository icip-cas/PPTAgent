"""The visual MCP must start over stdio and advertise its two review tools."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


class VisualMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_lists_review_tools(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pptagent-mcp-") as directory:
            workspace = Path(directory)
            (workspace / "task.json").write_text(
                json.dumps({"slides": 1, "aspect_ratio": "16:9", "language": "en"}),
                encoding="utf-8",
            )
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    str(ROOT / "scripts/visual_mcp.py"),
                    "--workspace",
                    str(workspace),
                ],
                env=os.environ.copy(),
            )
            async with (
                stdio_client(params) as (reader, writer),
                ClientSession(reader, writer) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                self.assertEqual(
                    {tool.name for tool in tools.tools},
                    {"review_slides", "review_deck"},
                )


if __name__ == "__main__":
    unittest.main()
