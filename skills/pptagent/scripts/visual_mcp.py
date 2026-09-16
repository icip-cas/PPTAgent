#!/usr/bin/env python3
"""Expose the skill's external visual review as a stdio MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pptagent_runtime.config import SKILL_ROOT, load_config, visual_settings


def create_server(
    workspace: Path,
    config_path: Path | None = None,
    env_path: Path | None = None,
) -> FastMCP:
    workspace = workspace.expanduser().resolve()
    if not (workspace / "task.json").is_file():
        raise ValueError("workspace must contain task.json; run the skill's init first")
    server = FastMCP("PPTAgent Visual Review")
    lock = asyncio.Lock()

    async def run_review(command: str) -> dict[str, Any]:
        async with lock:
            config = load_config(config_path, env_path)
            if config["mode"] != "text":
                raise ToolError("visual MCP requires mode: text in the skill config")
            settings = visual_settings(config)
            if not all(settings[key] for key in ("base_url", "model", "api_key")):
                raise ToolError("configure the visual endpoint, model, and API key")
            argv = [sys.executable, str(SKILL_ROOT / "scripts/pptagent.py")]
            if config_path:
                argv.extend(["--config", str(config_path.resolve())])
            if env_path:
                argv.extend(["--env", str(env_path.resolve())])
            argv.extend([command, "--workspace", str(workspace)])
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await process.communicate()
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError as exc:
                raise ToolError("visual review returned invalid JSON") from exc
            if process.returncode:
                raise ToolError(str(payload.get("error") or "visual review failed"))
            return payload

    @server.tool()
    async def review_slides() -> dict[str, Any]:
        """Render and review every HTML slide with the configured visual model."""
        return await run_review("review-slides")

    @server.tool()
    async def review_deck() -> dict[str, Any]:
        """Render and review the exported answer.pptx contact sheets."""
        return await run_review("review-deck")

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="PPTAgent visual review MCP")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--env", type=Path)
    args = parser.parse_args()
    create_server(args.workspace, args.config, args.env).run(show_banner=False)


if __name__ == "__main__":
    main()
