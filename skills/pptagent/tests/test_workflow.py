"""Acceptance regressions; render and PPTX fixtures isolate evidence validation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from pptagent_runtime import core
from pptagent_runtime.config import load_config
from pptagent_runtime.visual import _parse_json, validate_review

spec = importlib.util.spec_from_file_location("skill_cli", SCRIPTS / "pptagent.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

STRICT = {"delivery": {"mode": "strict"}}
DRAFT = {"delivery": {"mode": "best-effort"}}


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="pptagent-test-")
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        (self.workspace / "task.json").write_text(
            json.dumps(
                {
                    "slides": 1,
                    "aspect_ratio": "16:9",
                    "language": "en",
                }
            )
        )
        core.scaffold(self.workspace)
        self.slide = self.workspace / "slides/slide01.html"

    def save_render(self, deck: bool = False) -> None:
        image = self.workspace / "qa" / ("deck.jpg" if deck else "slide.jpg")
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(b"synthetic render fixture")
        inputs = (
            {"artifact_sha256": core.sha256(self.workspace / "answer.pptx")}
            if deck
            else core.input_snapshot(self.workspace, [self.slide])
        )
        render = {
            "inputs": inputs,
            "images": {str(image.relative_to(self.workspace)): core.sha256(image)},
        }
        state = core.load_state(self.workspace)
        if deck:
            state["renders"]["deck"] = render
        else:
            state["renders"]["slides"]["slides/slide01.html"] = render
        core.save_state(self.workspace, state)

    def review_slide(self) -> None:
        core.record_slide_review(
            self.workspace,
            "slides/slide01.html",
            "pass",
            "Fixture reviewed",
            [],
            "test",
        )

    def complete_fixture(self) -> None:
        self.save_render()
        self.review_slide()
        with zipfile.ZipFile(self.workspace / "answer.pptx", "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", "<slide/>")
            archive.writestr(
                "ppt/presentation.xml",
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:sldSz cx="12192000" cy="6858000"/></p:presentation>',
            )
        state = core.load_state(self.workspace)
        state["build"] = {
            "artifact_sha256": core.sha256(self.workspace / "answer.pptx"),
            "inputs": core.input_snapshot(self.workspace, [self.slide]),
        }
        core.save_state(self.workspace, state)
        self.save_render(deck=True)
        core.record_deck_review(self.workspace, "pass", "Fixture reviewed", [], "test")
        self.assertTrue(core.finalize(self.workspace, STRICT)["complete"])

    def test_re_reviewing_changed_html_does_not_make_old_pptx_current(self) -> None:
        self.complete_fixture()
        self.slide.write_text(
            self.slide.read_text().replace("audience-facing claim", "new content")
        )
        self.save_render()
        self.review_slide()
        for config in (STRICT, DRAFT):
            report = core.finalize(self.workspace, config)
            self.assertFalse(report["checks"]["build_current"])
            self.assertFalse(report["ok"])
            self.assertFalse(report["delivery_ready"])

    def test_shared_css_change_invalidates_review(self) -> None:
        css = self.workspace / "assets/theme.css"
        css.write_text("p { color: black; }")
        self.complete_fixture()
        css.write_text("p { display: none; }")
        self.assertTrue(core.review_gaps(self.workspace, [self.slide]))
        self.assertFalse(core.finalize(self.workspace, STRICT)["ok"])

    def test_cannot_record_review_of_missing_or_stale_render(self) -> None:
        with self.assertRaisesRegex(ValueError, "render"):
            self.review_slide()
        self.save_render()
        self.slide.write_text("<p>Changed since rendering</p>")
        with self.assertRaisesRegex(ValueError, "render"):
            self.review_slide()

    def test_modified_render_invalidates_review(self) -> None:
        self.complete_fixture()
        (self.workspace / "qa/slide.jpg").write_bytes(b"different image")
        self.assertFalse(core.finalize(self.workspace, STRICT)["ok"])

    def test_modified_pptx_requires_new_deck_render(self) -> None:
        self.complete_fixture()
        with (self.workspace / "answer.pptx").open("ab") as handle:
            handle.write(b"modified")
        with self.assertRaisesRegex(ValueError, "deck render"):
            core.record_deck_review(self.workspace, "pass", "Reviewed", [], "test")
        self.assertFalse(core.finalize(self.workspace, DRAFT)["ok"])

    def test_best_effort_does_not_claim_complete(self) -> None:
        self.complete_fixture()
        core.record_deck_review(
            self.workspace, "fail", "Visible layout issue", [], "test"
        )
        self.assertFalse(core.finalize(self.workspace, STRICT)["ok"])
        draft = core.finalize(self.workspace, DRAFT)
        self.assertTrue(draft["delivery_ready"])
        self.assertFalse(draft["complete"])

    def test_finalize_without_pptx_exits_nonzero(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "pptagent.py"),
                "finalize",
                "--workspace",
                str(self.workspace),
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["ok"])

    def test_doctor_marks_invalid_task_failed(self) -> None:
        (self.workspace / "task.json").write_text("{}")
        result = cli.doctor({"mode": "multimodal"}, self.workspace)
        self.assertFalse(result["ok"])
        self.assertFalse(result["checks"]["task"])
        self.assertIn("task", result["failed"])

    def test_contradictory_visual_pass_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot pass"):
            validate_review(
                {
                    "verdict": "pass",
                    "summary": "Unreadable",
                    "issues": [
                        {
                            "severity": "major",
                            "slide": 1,
                            "description": "Text clipped",
                            "suggested_fix": "Resize",
                        }
                    ],
                }
            )

    def test_json_is_not_silently_repaired(self) -> None:
        result = _parse_json(
            '{"verdict":"pass","summary":"Keep literal ,} text","issues":[]}'
        )
        self.assertEqual(result["summary"], "Keep literal ,} text")
        with self.assertRaises(json.JSONDecodeError):
            _parse_json('{"verdict":"pass","summary":"ok","issues":[],}')

    def test_explicit_missing_config_is_an_error(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config(self.workspace / "missing.yaml")

    def test_scaffold_preserves_authored_slides(self) -> None:
        self.slide.write_text("<p>Authored content</p>")
        core.scaffold(self.workspace)
        self.assertEqual(self.slide.read_text(), "<p>Authored content</p>")

    def test_duplicate_slide_numbers_are_rejected(self) -> None:
        (self.workspace / "slides/slide1.html").write_text("<p>Duplicate</p>")
        with self.assertRaisesRegex(ValueError, "unique"):
            core.slide_files(self.workspace)


if __name__ == "__main__":
    unittest.main()
