from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

from .config import SKILL_ROOT, node_environment
from .visual import validate_review

if TYPE_CHECKING:
    from playwright.async_api import Page, Route

ASPECTS = {
    "16:9": (1280, 720, 16 / 9),
    "4:3": (960, 720, 4 / 3),
    "A1": (2244, 3178, 23.39 / 33.11),
}
STATE_SCHEMA = "pptagent.standalone.state.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_task(workspace: Path) -> dict[str, Any]:
    path = workspace / "task.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path}")
    task = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(task, dict):
        raise TypeError("task.json must contain an object")
    for key in ("slides", "aspect_ratio", "language"):
        if task.get(key) in (None, ""):
            raise ValueError(f"task.json is missing {key!r}")
    if type(task["slides"]) is not int or task["slides"] < 1:
        raise ValueError("task.json slides must be a positive integer")
    if task["aspect_ratio"] not in ASPECTS:
        raise ValueError(f"unsupported aspect ratio {task['aspect_ratio']!r}")
    return {key: task[key] for key in ("slides", "aspect_ratio", "language")}


def slide_files(workspace: Path) -> list[Path]:
    files = list((workspace / "slides").glob("slide*.html"))
    for path in files:
        if not re.fullmatch(r"slide\d+\.html", path.name):
            raise ValueError(f"unexpected slide filename: {path.name}")
    files.sort(key=lambda path: int(path.stem.removeprefix("slide")))
    if [int(path.stem.removeprefix("slide")) for path in files] != list(
        range(1, len(files) + 1)
    ):
        raise ValueError("slide numbers must be unique and consecutive, starting at 1")
    return files


def load_state(workspace: Path) -> dict[str, Any]:
    path = workspace / "workspace-state.json"
    state = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if state.get("schema_version") not in (None, STATE_SCHEMA):
        raise ValueError("workspace-state.json belongs to an incompatible workflow")
    return {
        "schema_version": STATE_SCHEMA,
        "renders": state.get("renders", {"slides": {}, "deck": {}}),
        "reviews": state.get("reviews", {"slides": {}, "deck": {}}),
        "build": state.get("build", {}),
    }


def save_state(workspace: Path, state: dict[str, Any]) -> None:
    state["schema_version"] = STATE_SCHEMA
    target = workspace / "workspace-state.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(target)


def input_snapshot(workspace: Path, files: list[Path]) -> dict[str, Any]:
    # Hash shared resources as a whole; parsing CSS/JS dependency graphs is unnecessary.
    resources = [path for path in (workspace / "assets").rglob("*") if path.is_file()]
    resources += [
        path
        for path in (workspace / "slides").rglob("*")
        if path.is_file() and path.suffix.lower() != ".html"
    ]
    return {
        "task": load_task(workspace),
        "files": {
            str(path.relative_to(workspace)): sha256(path)
            for path in sorted(set(files + resources))
        },
    }


def scaffold(workspace: Path) -> dict[str, Any]:
    task = load_task(workspace)
    width, height, _ = ASPECTS[task["aspect_ratio"]]
    template = (SKILL_ROOT / "assets/slide-template.html").read_text(encoding="utf-8")
    for name in ("slides", "assets"):
        (workspace / name).mkdir(exist_ok=True)
    created = []
    for number in range(1, task["slides"] + 1):
        path = workspace / "slides" / f"slide{number:02d}.html"
        if path.exists():
            continue
        source = template
        for key, value in {
            "LANGUAGE": task["language"],
            "WIDTH": width,
            "HEIGHT": height,
            "SLIDE_NUMBER": f"{number:02d}",
        }.items():
            source = source.replace("{{" + key + "}}", str(value))
        path.write_text(source, encoding="utf-8")
        created.append(str(path.relative_to(workspace)))
    return {"ok": True, "task": task, "created": created}


def render_current(
    workspace: Path, render: dict[str, Any], inputs: dict[str, Any]
) -> bool:
    images = render.get("images", {})
    return (
        render.get("inputs") == inputs
        and bool(images)
        and all(
            (workspace / name).is_file() and sha256(workspace / name) == digest
            for name, digest in images.items()
        )
    )


async def open_slide(
    page: Page, path: Path, workspace: Path, inputs: dict[str, Any]
) -> None:
    tracked = {(workspace / name).resolve() for name in inputs["files"]}
    blocked: list[str] = []

    async def local_resource(route: Route) -> None:
        url = urlparse(route.request.url)
        if url.scheme == "file" and Path(unquote(url.path)).resolve() in tracked:
            await route.continue_()
        else:
            blocked.append(route.request.url)
            await route.abort()

    await page.route("**/*", local_resource)
    try:
        await page.goto(path.resolve().as_uri(), wait_until="load", timeout=15_000)
        await page.wait_for_function(
            "() => document.fonts.status === 'loaded'", timeout=8_000
        )
        if blocked:
            raise ValueError(
                f"untracked render resources; place dependencies in assets/: {blocked}"
            )
    finally:
        await page.unroute("**/*", local_resource)


async def render_slides(workspace: Path) -> dict[str, Any]:
    from deeppresenter.utils.webview import PlaywrightConverter

    task = load_task(workspace)
    files = slide_files(workspace)
    if not files:
        raise ValueError("no slide HTML files selected")
    output_dir = workspace / "qa" / "slides"
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height, _ratio = ASPECTS[task["aspect_ratio"]]
    outputs: list[str] = []
    state = load_state(workspace)
    try:
        async with PlaywrightConverter() as converter:
            if converter.page is None:
                raise RuntimeError("Playwright page is unavailable")
            await converter.page.set_viewport_size({"width": width, "height": height})
            for html_path in files:
                inputs = input_snapshot(workspace, [html_path])
                await open_slide(converter.page, html_path, workspace, inputs)
                destination = output_dir / f"{html_path.stem}.jpg"
                await converter.page.screenshot(
                    path=str(destination), type="jpeg", quality=90, full_page=False
                )
                outputs.append(str(destination.relative_to(workspace)))
                state["renders"]["slides"][str(html_path.relative_to(workspace))] = {
                    "inputs": inputs,
                    "images": {outputs[-1]: sha256(destination)},
                }
        save_state(workspace, state)
        return {"ok": True, "renders": outputs, "count": len(outputs)}
    finally:
        await PlaywrightConverter.shutdown()


def record_slide_review(
    workspace: Path,
    slide: str,
    verdict: str,
    summary: str,
    issues: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    path = (workspace / slide).resolve()
    if (
        not path.is_relative_to(workspace)
        or not path.is_file()
        or path.suffix != ".html"
    ):
        raise ValueError(f"invalid slide path: {slide}")
    relative = str(path.relative_to(workspace))
    state = load_state(workspace)
    render = state["renders"]["slides"].get(relative, {})
    if not render_current(workspace, render, input_snapshot(workspace, [path])):
        raise ValueError(
            "missing or stale slide render; run review-slides and inspect it first"
        )
    record = {
        **validate_review({"verdict": verdict, "summary": summary, "issues": issues}),
        "review_mode": mode,
        "render": render,
    }
    state["reviews"]["slides"][relative] = record
    save_state(workspace, state)
    return {"slide": relative, **record}


def review_gaps(workspace: Path, files: list[Path]) -> list[str]:
    evidence = load_state(workspace)["reviews"]["slides"]
    gaps: list[str] = []
    for path in files:
        relative = str(path.relative_to(workspace))
        record = evidence.get(relative) or {}
        if not render_current(
            workspace, record.get("render", {}), input_snapshot(workspace, [path])
        ):
            gaps.append(f"{relative}: missing or stale review")
        elif record.get("ok") is not True:
            gaps.append(f"{relative}: blocker or major issue remains")
    return gaps


def pptx_info(path: Path) -> tuple[int, str]:
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"corrupt PPTX member: {bad}")
        count = len(
            [
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ]
        )
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
    size = root.find(
        "{http://schemas.openxmlformats.org/presentationml/2006/main}sldSz"
    )
    if size is None:
        raise ValueError("PPTX has no slide size")
    ratio = int(size.attrib["cx"]) / int(size.attrib["cy"])
    for name, (_width, _height, expected) in ASPECTS.items():
        if abs(ratio - expected) < 0.03:
            return count, name
    return count, f"{ratio:.4f}"


async def build(workspace: Path, config: dict[str, Any]) -> dict[str, Any]:
    from deeppresenter.utils.webview import SCRIPT_PATH

    task = load_task(workspace)
    files = slide_files(workspace)
    if len(files) != task["slides"]:
        raise ValueError(f"expected {task['slides']} slides, found {len(files)}")
    inputs = input_snapshot(workspace, files)
    renders = load_state(workspace)["renders"]["slides"]
    if any(
        not render_current(
            workspace,
            renders.get(str(path.relative_to(workspace)), {}),
            input_snapshot(workspace, [path]),
        )
        for path in files
    ):
        raise ValueError("missing or stale slide renders; run review-slides first")
    gaps = review_gaps(workspace, files)
    delivery_mode = str((config.get("delivery") or {}).get("mode") or "strict")
    if gaps and delivery_mode == "strict":
        raise ValueError("visual review gate failed: " + "; ".join(gaps))
    answer = workspace / "answer.pptx"
    command = [
        "node",
        str(SCRIPT_PATH),
        "--layout",
        task["aspect_ratio"],
        "--output",
        str(answer),
    ]
    for path in files:
        command.extend(["--html", str(path)])
    process = await asyncio.create_subprocess_exec(
        *command,
        env=node_environment(),
        cwd=SKILL_ROOT,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError((stderr or stdout).decode("utf-8", errors="replace"))
    count, aspect = pptx_info(answer)
    if count != task["slides"] or aspect != task["aspect_ratio"]:
        raise ValueError(f"built PPTX mismatch: slides={count}, aspect_ratio={aspect}")
    state = load_state(workspace)
    record = {
        "ok": True,
        "artifact": answer.name,
        "artifact_sha256": sha256(answer),
        "inputs": inputs,
        "slides": count,
        "aspect_ratio": aspect,
        "quality_warnings": gaps,
    }
    state["build"] = record
    state["reviews"]["deck"] = {}
    save_state(workspace, state)
    return record


def _contact_sheets(pages: list[Path], output_dir: Path) -> list[Path]:
    contacts: list[Path] = []
    for offset in range(0, len(pages), 4):
        group = pages[offset : offset + 4]
        sheet = Image.new("RGB", (1280, 720), "#101826")
        draw = ImageDraw.Draw(sheet)
        for index, path in enumerate(group):
            with Image.open(path) as source:
                image = source.convert("RGB")
                image.thumbnail((620, 330))
            x = (index % 2) * 640 + (640 - image.width) // 2
            y = (index // 2) * 360 + (360 - image.height) // 2
            sheet.paste(image, (x, y))
            draw.rectangle((x + 4, y + 4, x + 38, y + 28), fill="#101826")
            draw.text((x + 10, y + 7), str(offset + index + 1), fill="white")
        destination = output_dir / f"contact-{offset // 4 + 1:02d}.jpg"
        sheet.save(destination, quality=90)
        contacts.append(destination)
    return contacts


def render_deck(workspace: Path) -> dict[str, Any]:
    import pymupdf

    answer = workspace / "answer.pptx"
    if not answer.is_file():
        raise FileNotFoundError(f"missing {answer}; run build first")
    artifact_hash = sha256(answer)
    output_dir = workspace / "qa" / "deck"
    output_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("page-*.jpg", "contact-*.jpg", "*.pdf"):
        for path in output_dir.glob(pattern):
            path.unlink()
    with tempfile.TemporaryDirectory(prefix="pptagent-lo-") as temp:
        runtime = Path(temp) / "runtime"
        config_dir = Path(temp) / "config"
        runtime.mkdir(mode=0o700)
        config_dir.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "HOME": temp,
                "XDG_CONFIG_HOME": str(config_dir),
                "XDG_RUNTIME_DIR": str(runtime),
                "GSETTINGS_BACKEND": "memory",
                "SAL_USE_VCLPLUGIN": "svp",
            }
        )
        subprocess.run(
            [
                "libreoffice",
                f"-env:UserInstallation={Path(temp).as_uri()}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf:impress_pdf_Export",
                "--outdir",
                str(output_dir),
                str(answer),
            ],
            cwd=workspace,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=480,
        )
    pdf = output_dir / f"{answer.stem}.pdf"
    with pymupdf.open(pdf) as document:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.7, 1.7), alpha=False)
            pixmap.save(output_dir / f"page-{index:02d}.jpg")
    pages = sorted(output_dir.glob("page-*.jpg"))
    contacts = _contact_sheets(pages, output_dir)
    state = load_state(workspace)
    state["renders"]["deck"] = {
        "inputs": {"artifact_sha256": artifact_hash},
        "images": {str(path.relative_to(workspace)): sha256(path) for path in contacts},
    }
    save_state(workspace, state)
    return {
        "ok": True,
        "artifact_sha256": artifact_hash,
        "pages": [str(path.relative_to(workspace)) for path in pages],
        "contact_sheets": [str(path.relative_to(workspace)) for path in contacts],
    }


def record_deck_review(
    workspace: Path,
    verdict: str,
    summary: str,
    issues: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    answer = workspace / "answer.pptx"
    if not answer.is_file():
        raise FileNotFoundError(answer)
    state = load_state(workspace)
    render = state["renders"]["deck"]
    if not render_current(workspace, render, {"artifact_sha256": sha256(answer)}):
        raise ValueError(
            "missing or stale deck render; run review-deck and inspect it first"
        )
    record = {
        **validate_review({"verdict": verdict, "summary": summary, "issues": issues}),
        "review_mode": mode,
        "render": render,
    }
    state["reviews"]["deck"] = record
    save_state(workspace, state)
    return record


def finalize(workspace: Path, config: dict[str, Any]) -> dict[str, Any]:
    task = load_task(workspace)
    files = slide_files(workspace)
    state = load_state(workspace)
    answer = workspace / "answer.pptx"
    answer_exists = answer.is_file() and answer.stat().st_size > 0
    if answer_exists:
        count, aspect = pptx_info(answer)
        artifact_hash = sha256(answer)
    else:
        count, aspect, artifact_hash = 0, "unknown", None
    deck = state["reviews"]["deck"]
    checks = {
        "slide_html_count": len(files) == task["slides"],
        "slide_reviews_current": not review_gaps(workspace, files),
        "answer_exists": answer_exists,
        "pptx_structure": count == task["slides"] and aspect == task["aspect_ratio"],
        "build_current": bool(
            answer_exists
            and state["build"].get("artifact_sha256") == artifact_hash
            and state["build"].get("inputs") == input_snapshot(workspace, files)
        ),
        "deck_review_current": bool(
            answer_exists
            and deck.get("ok") is True
            and render_current(
                workspace, deck.get("render", {}), {"artifact_sha256": artifact_hash}
            )
        ),
    }
    complete = all(checks.values())
    delivery_ready = bool(
        checks["answer_exists"] and checks["pptx_structure"] and checks["build_current"]
    )
    accepted = complete or (
        config["delivery"]["mode"] == "best-effort" and delivery_ready
    )
    report = {
        "ok": accepted,
        "schema_version": "pptagent.standalone.final.v1",
        "complete": complete,
        "delivery_ready": accepted,
        "checks": checks,
        "artifact": answer.name if answer_exists else None,
        "artifact_sha256": artifact_hash,
        "slides": count,
        "aspect_ratio": aspect,
    }
    (workspace / "final-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
