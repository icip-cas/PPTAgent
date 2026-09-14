#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from pptagent_runtime import core
from pptagent_runtime.config import (
    SKILL_ROOT,
    load_config,
    node_environment,
    visual_settings,
)
from pptagent_runtime.visual import review_images


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_issues(value: str) -> list[dict[str, Any]]:
    payload = json.loads(value)
    if not isinstance(payload, list):
        raise TypeError("--issues-json must be a JSON list")
    return payload


def doctor(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    checks = {"python:version": sys.version_info >= (3, 11)}
    errors: dict[str, str] = {}
    for module in ("yaml", "PIL", "pymupdf", "playwright", "deeppresenter"):
        checks[f"python:{module}"] = importlib.util.find_spec(module) is not None
    checks["command:libreoffice"] = shutil.which("libreoffice") is not None
    env = node_environment()
    checks["command:node"] = shutil.which("node", path=env["PATH"]) is not None
    if checks["python:playwright"]:
        expected = json.loads((SKILL_ROOT / "package.json").read_text())[
            "dependencies"
        ]["playwright"]
        checks["playwright:version"] = (
            importlib.metadata.version("playwright") == expected
        )
    if checks["python:deeppresenter"] and checks["command:node"]:
        spec = importlib.util.find_spec("deeppresenter")
        converter = (
            Path(next(iter(spec.submodule_search_locations)))
            / "html2pptx/html2pptx_cli.js"
        )
        checks["html2pptx:script"] = converter.is_file()
        probe = subprocess.run(
            [
                "node",
                "-e",
                """
const requireRuntime = require('module').createRequire(process.argv[1]);
for (const name of ['fast-glob', 'minimist', 'pptxgenjs', 'sharp']) requireRuntime(name);
const pw = requireRuntime('playwright');
if (requireRuntime('playwright/package.json').version !== process.argv[2])
  throw Error('Python and Node Playwright versions must match');
if (!require('fs').existsSync(pw.chromium.executablePath()))
  throw Error('Chromium is missing; run python3 -m playwright install chromium');
""",
                str(converter),
                json.loads((SKILL_ROOT / "package.json").read_text())["dependencies"][
                    "playwright"
                ],
            ],
            env=env,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        checks["html2pptx:runtime"] = probe.returncode == 0
        if probe.returncode:
            errors["html2pptx:runtime"] = probe.stderr.strip()
    if config["mode"] == "text":
        settings = visual_settings(config)
        checks["visual:base_url"] = bool(settings["base_url"])
        checks["visual:model"] = bool(settings["model"])
        checks[f"visual:key:{settings['api_key_env']}"] = bool(settings["api_key"])
    if (workspace / "task.json").is_file():
        try:
            core.load_task(workspace)
            checks["task"] = True
        except (ValueError, TypeError) as exc:
            checks["task"] = False
            errors["task"] = str(exc)
    failed = [name for name, value in checks.items() if not value]
    return {
        "ok": not failed,
        "mode": config["mode"],
        "checks": checks,
        "errors": errors,
        "failed": failed,
    }


def init_workspace(args: argparse.Namespace) -> dict[str, Any]:
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    task_path = workspace / "task.json"
    if task_path.exists() and not args.force:
        raise FileExistsError(f"refusing to replace {task_path}; pass --force")
    if args.slides < 1:
        raise ValueError("slides must be positive")
    task = {
        "slides": args.slides,
        "aspect_ratio": args.aspect_ratio,
        "language": args.language,
    }
    task_path.write_text(
        json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"ok": True, "workspace": str(workspace), "task": task}


async def review_slides(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    rendered = await core.render_slides(workspace)
    if config["mode"] == "multimodal":
        return {
            **rendered,
            "review_mode": "host",
            "instruction": (
                "Inspect every render with the host image viewer, then call "
                "record-slide-review for each current slide."
            ),
        }
    task = core.load_task(workspace)
    results = []
    for slide, image in zip(core.slide_files(workspace), rendered["renders"]):
        number = slide.stem.removeprefix("slide")
        report = review_images(
            config,
            [workspace / image],
            f"Review slide {number} of {task['slides']} for layout, readability, "
            "visual quality, and content suitability.",
        )
        results.append(
            core.record_slide_review(
                workspace,
                str(slide.relative_to(workspace)),
                report["verdict"],
                report["summary"],
                report["issues"],
                "external-visual",
            )
        )
    return {
        "ok": all(item["ok"] for item in results),
        "review_mode": "external-visual",
        "results": results,
    }


def review_deck(config: dict[str, Any], workspace: Path) -> dict[str, Any]:
    rendered = core.render_deck(workspace)
    if config["mode"] == "multimodal":
        return {
            **rendered,
            "review_mode": "host",
            "instruction": (
                "Inspect all contact sheets with the host image viewer, then call "
                "record-deck-review."
            ),
        }
    images = [workspace / value for value in rendered["contact_sheets"]]
    report = review_images(
        config,
        images,
        "Review this complete presentation for consistency, narrative flow, "
        "readability, clipping, overlap, and visual outliers. Identify slide numbers.",
    )
    record = core.record_deck_review(
        workspace,
        report["verdict"],
        report["summary"],
        report["issues"],
        "external-visual",
    )
    return {
        **rendered,
        "ok": record["ok"],
        "review_mode": "external-visual",
        "review": record,
    }


def make_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Standalone PPTAgent Skill tools")
    root.add_argument("--config", type=Path)
    root.add_argument("--env", type=Path)
    sub = root.add_subparsers(dest="command", required=True)
    for name in (
        "doctor",
        "scaffold",
        "review-slides",
        "build",
        "review-deck",
        "finalize",
    ):
        command = sub.add_parser(name)
        command.add_argument("--workspace", type=Path, default=Path.cwd())
    init = sub.add_parser("init")
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--slides", type=int, required=True)
    init.add_argument("--aspect-ratio", choices=tuple(core.ASPECTS), default="16:9")
    init.add_argument("--language", default="zh")
    init.add_argument("--force", action="store_true")
    slide = sub.add_parser("record-slide-review")
    slide.add_argument("--workspace", type=Path, default=Path.cwd())
    slide.add_argument("--slide", required=True)
    slide.add_argument(
        "--verdict", choices=("pass", "fail", "unjudgeable"), required=True
    )
    slide.add_argument("--summary", required=True)
    slide.add_argument("--issues-json", default="[]")
    deck = sub.add_parser("record-deck-review")
    deck.add_argument("--workspace", type=Path, default=Path.cwd())
    deck.add_argument(
        "--verdict", choices=("pass", "fail", "unjudgeable"), required=True
    )
    deck.add_argument("--summary", required=True)
    deck.add_argument("--issues-json", default="[]")
    return root


def main() -> None:
    args = make_parser().parse_args()
    try:
        config = load_config(args.config, args.env)
        workspace = args.workspace.resolve()
        if args.command == "doctor":
            result = doctor(config, workspace)
        elif args.command == "init":
            result = init_workspace(args)
        elif args.command == "scaffold":
            result = core.scaffold(workspace)
        elif args.command == "review-slides":
            result = asyncio.run(review_slides(config, workspace))
        elif args.command == "record-slide-review":
            result = core.record_slide_review(
                workspace,
                args.slide,
                args.verdict,
                args.summary,
                parse_issues(args.issues_json),
                "host",
            )
        elif args.command == "build":
            result = asyncio.run(core.build(workspace, config))
        elif args.command == "review-deck":
            result = review_deck(config, workspace)
        elif args.command == "record-deck-review":
            result = core.record_deck_review(
                workspace,
                args.verdict,
                args.summary,
                parse_issues(args.issues_json),
                "host",
            )
        elif args.command == "finalize":
            result = core.finalize(workspace, config)
        else:
            raise AssertionError(args.command)
        emit(result)
        if isinstance(result, dict) and result.get("ok") is False:
            raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001 - CLI errors use the JSON protocol.
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise SystemExit(2)


if __name__ == "__main__":
    main()
