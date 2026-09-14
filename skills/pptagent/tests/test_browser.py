"""Browser checks for local dependencies and export-compatible canvas sizing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from pptagent_runtime import core

from deeppresenter.utils.webview import PlaywrightConverter


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="pptagent-browser-test-")
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        (self.workspace / "task.json").write_text(
            json.dumps(
                {
                    "slides": 1,
                    "aspect_ratio": "4:3",
                    "language": "en",
                }
            )
        )
        core.scaffold(self.workspace)
        self.slide = self.workspace / "slides/slide01.html"
        self.slide.write_text(
            '<!doctype html><html><head><link rel="stylesheet" href="../assets/theme.css"></head><body><p>Visible content</p><a href="https://example.com">Source</a></body></html>'
        )
        self.css = self.workspace / "assets/theme.css"
        self.css.write_text(
            "html,body {width:960px;height:720px;margin:0} p {font-size:24px}"
        )

    async def asyncTearDown(self) -> None:
        await PlaywrightConverter.shutdown()

    async def test_canvas_in_external_css_and_ordinary_links_are_supported(
        self,
    ) -> None:
        renders = await core.render_slides(self.workspace)
        self.assertEqual(renders["count"], 1)
        await core.build(self.workspace, {"delivery": {"mode": "best-effort"}})
        self.assertEqual(core.pptx_info(self.workspace / "answer.pptx"), (1, "4:3"))

    async def test_viewport_dependent_wrong_canvas_is_rejected(self) -> None:
        self.css.write_text(
            "html,body {width:100vw;height:720px;margin:0} p {font-size:24px}"
        )
        await core.render_slides(self.workspace)
        with self.assertRaisesRegex(RuntimeError, "dimensions"):
            await core.build(self.workspace, {"delivery": {"mode": "best-effort"}})

    async def test_plain_div_text_is_supported(self) -> None:
        self.slide.write_text(
            self.slide.read_text().replace(
                "<p>Visible content</p>", "<div>Plain text</div>"
            )
        )
        await core.render_slides(self.workspace)
        await core.build(self.workspace, {"delivery": {"mode": "best-effort"}})
        with zipfile.ZipFile(self.workspace / "answer.pptx") as archive:
            self.assertIn(b"Plain text", archive.read("ppt/slides/slide1.xml"))

    async def test_converter_rejects_unwrapped_text_in_layout_container(self) -> None:
        self.slide.write_text(
            self.slide.read_text().replace(
                "<p>Visible content</p>",
                '<div style="display:flex">Unwrapped text</div>',
            )
        )
        await core.render_slides(self.workspace)
        with self.assertRaisesRegex(RuntimeError, "unwrapped text"):
            await core.build(self.workspace, {"delivery": {"mode": "best-effort"}})

    async def test_remote_render_dependency_is_rejected(self) -> None:
        self.css.write_text(
            '@import url("https://example.invalid/theme.css"); html,body {width:960px;height:720px;margin:0}'
        )
        with self.assertRaisesRegex(ValueError, "untracked render resources"):
            await core.render_slides(self.workspace)


if __name__ == "__main__":
    unittest.main()
