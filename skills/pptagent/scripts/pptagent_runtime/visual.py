from __future__ import annotations

import base64
import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .config import visual_settings

SYSTEM_PROMPT = """You are a strict presentation visual reviewer. Judge only visible audience impact. Return one JSON object with verdict (pass, fail, or unjudgeable), summary, and issues. Each issue must contain severity (blocker, major, or minor), slide, description, and suggested_fix. Fail only for blocker or major issues such as clipping, overlap, unreadable text, broken images, severe imbalance, or materially inconsistent design."""


def validate_review(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("verdict") not in {
        "pass",
        "fail",
        "unjudgeable",
    }:
        raise ValueError("review must contain a valid verdict")
    if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
        raise ValueError("review summary must be nonempty text")
    if not isinstance(payload.get("issues"), list):
        raise TypeError("review issues must be a list")
    for issue in payload["issues"]:
        if not isinstance(issue, dict) or issue.get("severity") not in {
            "blocker",
            "major",
            "minor",
        }:
            raise ValueError("each issue must contain a valid severity")
        if type(issue.get("slide")) is not int or issue["slide"] < 1:
            raise ValueError("each issue must identify a positive slide number")
        if any(
            not isinstance(issue.get(key), str) or not issue[key].strip()
            for key in ("description", "suggested_fix")
        ):
            raise ValueError("each issue must contain a description and suggested_fix")
        if payload["verdict"] == "pass" and issue["severity"] in {"blocker", "major"}:
            raise ValueError("a review with blocker or major issues cannot pass")
    return {**payload, "ok": payload["verdict"] == "pass"}


def _parse_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL)
    return validate_review(json.loads(fenced.group(1) if fenced else candidate))


def review_images(
    config: dict[str, Any], image_paths: list[Path], context: str
) -> dict[str, Any]:
    settings = visual_settings(config)
    if not settings["base_url"] or not settings["model"] or not settings["api_key"]:
        raise ValueError(
            "text mode requires visual.base_url, visual.model, and VISUAL_API_KEY"
        )
    content: list[dict[str, Any]] = [{"type": "text", "text": context}]
    for path in image_paths:
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            }
        )
    body = json.dumps(
        {
            "model": settings["model"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        settings["base_url"] + "/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {settings['api_key']}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(
        request, timeout=settings["timeout_seconds"]
    ) as response:
        payload = json.loads(response.read().decode("utf-8"))
    message = payload["choices"][0]["message"]["content"]
    if isinstance(message, list):
        message = "\n".join(
            str(item.get("text") or "") for item in message if isinstance(item, dict)
        )
    return _parse_json(str(message))
