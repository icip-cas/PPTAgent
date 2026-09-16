"""Client registration regressions."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="pptagent-install-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()

    def install(self, client: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/install.py"),
                "--client",
                client,
                "--home",
                str(self.home),
                "--skip-runtime",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_opencode_registration_is_repeatable(self) -> None:
        for _ in range(2):
            result = self.install("opencode")
            self.assertEqual(result.returncode, 0, result.stderr)
        target = self.home / ".config/opencode/skills/pptagent"
        self.assertEqual(list(target.rglob("SKILL.md")), [target / "SKILL.md"])
        registration = (target / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(str(ROOT / "SKILL.md"), registration)
        self.assertIn(sys.executable, registration)

    def test_opencode_registration_preserves_existing_skill(self) -> None:
        target = self.home / ".config/opencode/skills/pptagent"
        target.mkdir(parents=True)
        skill = target / "SKILL.md"
        skill.write_text("user-owned skill", encoding="utf-8")
        self.assertEqual(self.install("opencode").returncode, 2)
        self.assertEqual(skill.read_text(encoding="utf-8"), "user-owned skill")


if __name__ == "__main__":
    unittest.main()
