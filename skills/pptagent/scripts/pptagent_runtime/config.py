from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import yaml

SKILL_ROOT = Path(__file__).resolve().parents[2]


def _load_env(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def load_config(
    config_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    _load_env((env_path or SKILL_ROOT / ".env").resolve())
    path = (config_path or SKILL_ROOT / "config.yaml").resolve()
    if config_path is None and not path.is_file():
        path = SKILL_ROOT / "config.example.yaml"
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise TypeError("config.yaml must contain a YAML object")
    mode = str(payload.get("mode") or "multimodal").strip().lower()
    if mode not in {"multimodal", "text"}:
        raise ValueError("mode must be multimodal or text")
    delivery = payload.get("delivery") or {}
    delivery_mode = delivery.get("mode", "strict")
    if delivery_mode not in {"strict", "best-effort"}:
        raise ValueError("delivery.mode must be strict or best-effort")
    if delivery.get("output", "answer.pptx") != "answer.pptx":
        raise ValueError("output is fixed at answer.pptx; remove delivery.output")
    return {
        "mode": mode,
        "visual": payload.get("visual") or {},
        "delivery": {"mode": delivery_mode},
    }


def node_environment() -> dict[str, str]:
    env = os.environ.copy()
    spec = importlib.util.find_spec("playwright")
    if spec and spec.submodule_search_locations:
        driver = Path(next(iter(spec.submodule_search_locations))) / "driver"
        env["PATH"] = str(driver) + os.pathsep + env.get("PATH", "")
    env["NODE_PATH"] = (
        str(SKILL_ROOT / "node_modules") + os.pathsep + env.get("NODE_PATH", "")
    )
    return env


def visual_settings(config: dict[str, Any]) -> dict[str, Any]:
    visual = config.get("visual") or {}
    key_name = str(visual.get("api_key_env") or "VISUAL_API_KEY")
    return {
        "base_url": str(visual.get("base_url") or "").rstrip("/"),
        "model": str(visual.get("model") or ""),
        "api_key_env": key_name,
        "api_key": os.environ.get(key_name, ""),
        "timeout_seconds": int(visual.get("timeout_seconds") or 300),
    }
