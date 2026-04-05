"""Tests for deeppresenter CLI commands module."""

from __future__ import annotations

import ast
from pathlib import Path


COMMANDS_FILE = Path(__file__).parent.parent / "cli" / "commands.py"


def _top_level_tui_imports(source: str) -> list[str]:
    """Return any top-level import of deeppresenter.tui found in the source."""
    tree = ast.parse(source)
    found = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.startswith("deeppresenter.tui"):
                found.append(module)
    return found


def test_tui_not_imported_at_module_level():
    """TUI imports must be lazy (inside functions) so onboard/generate work
    even when deeppresenter.tui.app is unavailable (e.g. missing in installed pkg).
    """
    source = COMMANDS_FILE.read_text(encoding="utf-8")
    bad_imports = _top_level_tui_imports(source)
    assert bad_imports == [], (
        f"Found top-level TUI import(s) in commands.py: {bad_imports}. "
        "These must be moved inside the tui() function to avoid breaking other "
        "commands when the tui subpackage is missing."
    )
