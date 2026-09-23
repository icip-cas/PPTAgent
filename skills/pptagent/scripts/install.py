#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from pptagent_runtime.config import node_environment


def register_opencode(source: Path, base: Path) -> Path:
    """Create the lightweight skill entry that OpenCode discovers."""
    target = base / "pptagent"
    marker = target / ".pptagent-source"
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not marker.is_file():
            raise ValueError(f"refusing to replace {target}")
        if marker.read_text(encoding="utf-8").strip() != str(source):
            raise ValueError(f"refusing to replace {target} from another checkout")
    target.mkdir(parents=True, exist_ok=True)
    frontmatter = (source / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
    (target / "SKILL.md").write_text(
        f"---{frontmatter}---\n\n# PPTAgent for OpenCode\n\n"
        f"Read and follow the full skill at `{source / 'SKILL.md'}`.\n"
        f"Resolve SKILL_ROOT to `{source}` and use `{Path(sys.executable).absolute()}` "
        "as SKILL_PYTHON. References and scripts are under SKILL_ROOT.\n",
        encoding="utf-8",
    )
    marker.write_text(str(source) + "\n", encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Register this PPTAgent Skill")
    parser.add_argument(
        "--client",
        choices=("claude", "codex", "gigacode", "opencode"),
        required=True,
    )
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--skip-runtime", action="store_true")
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    base = (
        args.home
        / {
            "claude": ".claude/skills",
            "codex": ".agents/skills",
            "gigacode": ".gigacode/skills",
            "opencode": ".config/opencode/skills",
        }[args.client]
    )
    target = base / "pptagent"
    if (
        args.client != "opencode"
        and (target.exists() or target.is_symlink())
        and target.resolve() != source
    ):
        parser.exit(2, f"pptagent-install: error: refusing to replace {target}\n")
    if not args.skip_runtime:
        npm = shutil.which("npm")
        if npm is None:
            parser.exit(2, "pptagent-install: error: npm is required\n")
        subprocess.run(
            [npm, "ci", "--prefix", str(source)], check=True, env=node_environment()
        )
    if args.client == "opencode":
        try:
            target = register_opencode(source, base)
        except ValueError as exc:
            parser.exit(2, f"pptagent-install: error: {exc}\n")
    else:
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
