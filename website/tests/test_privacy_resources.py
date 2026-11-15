"""Unit tests for the generated-site privacy guard. No network or external dependencies."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-privacy-resources.py"
spec = importlib.util.spec_from_file_location("privacy_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)


class PrivacyGuardTests(unittest.TestCase):
    def check(self, name: str, text: str) -> list[str]:
        with TemporaryDirectory() as td:
            page = Path(td, name)
            page.write_text(text, encoding="utf-8")
            return guard.inspect_file(page)

    def test_block_remote_tracking_script(self):
        result = self.check("index.html", '<script src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>')
        self.assertTrue(result)

    def test_block_remote_font_stylesheet(self):
        result = self.check("index.html", '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto">')
        self.assertTrue(result)

    def test_block_youtube_thumbnail(self):
        result = self.check("index.html", '<img src="https://i.ytimg.com/vi/example/hqdefault.jpg">')
        self.assertTrue(result)

    def test_block_css_import(self):
        result = self.check("style.css", '@import url("https://fonts.googleapis.com/css2?family=Roboto");')
        self.assertTrue(result)

    def test_block_dynamic_js_endpoint(self):
        result = self.check("app.js", 'const s = "https://snap.licdn.com/li.lms-analytics/insight.min.js";')
        self.assertTrue(result)

    def test_allow_click_through_external_link(self):
        result = self.check("index.html", '<a href="https://youtu.be/example" target="_blank">Watch</a>')
        self.assertEqual(result, [])

    def test_allow_first_party_assets(self):
        result = self.check("index.html", '<script src="/assets/ok-ai-lite-preview.js"></script><img src="/images/local.webp">')
        self.assertEqual(result, [])

    def test_no_empty_site_pass(self):
        with TemporaryDirectory() as td:
            self.assertTrue(guard.scan(Path(td)))


if __name__ == "__main__":
    unittest.main()
