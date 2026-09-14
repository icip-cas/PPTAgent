#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from pptagent_runtime.config import node_environment


def main() -> None:
    parser = argparse.ArgumentParser(description="Register this PPTAgent Skill")
    parser.add_argument("--client", choices=("claude", "codex"), required=True)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--skip-runtime", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    base = args.home / (
        ".claude/skills" if args.client == "claude" else ".agents/skills"
    )
    target = base / "pptagent"
    if (target.exists() or target.is_symlink()) and target.resolve() != source:
        parser.exit(2, f"pptagent-install: error: refusing to replace {target}\n")
    if not args.skip_runtime:
        npm = shutil.which("npm")
        if npm is None:
            parser.exit(2, "pptagent-install: error: npm is required\n")
        subprocess.run(
            [npm, "ci", "--prefix", str(source)], check=True, env=node_environment()
        )
    base.mkdir(parents=True, exist_ok=True)
    if not target.is_symlink():
        target.symlink_to(source, target_is_directory=True)
    print(
        json.dumps(
            {
                "ok": True,
                "client": args.client,
                "skill": str(target),
                "source": str(source),
            }
        )
    )


if __name__ == "__main__":
    main()
