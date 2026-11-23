"""Regression tests for the widget guard used on preview and production."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from retired_widgets import check_retired_widgets


class RetiredWidgetTests(unittest.TestCase):
    def check(self, relative, contents):
        with TemporaryDirectory() as directory:
            site = Path(directory)
            path = site / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
            check_retired_widgets(site)

    def test_rejects_homepage_demo_loader(self):
        with self.assertRaisesRegex(SystemExit, r"ok-ai-floating-demo\.js in index\.html"):
            self.check("index.html", '<script>script.src = "/assets/ok-ai-floating-demo.js";</script>')

    def test_rejects_lite_loader_on_nested_page(self):
        with self.assertRaisesRegex(SystemExit, r"ok-ai-lite-preview\.js in ai/index\.html"):
            self.check("ai/index.html", '<script src="../assets/ok-ai-lite-preview.js"></script>')

    def test_rejects_stylesheet_loader_with_cache_buster(self):
        with self.assertRaisesRegex(SystemExit, r"ok-ai-floating-demo\.css in index\.html"):
            self.check("index.html", '<link rel="stylesheet" href="/assets/ok-ai-floating-demo.css?v=1">')

    def test_rejects_unreferenced_widget_assets(self):
        for name in ("ok-ai-floating-demo.js", "ok-ai-lite-preview.js", "ok-ai-floating-demo.css"):
            with self.subTest(name=name), self.assertRaisesRegex(SystemExit, "widget asset shipped"):
                self.check(f"assets/legacy/{name}", "")

    def test_rejects_widget_markup_and_bundled_code(self):
        for relative, contents in (
            ("ai/index.html", '<div id="okai-floating-demo"></div>'),
            ("assets/site.mjs", 'root.id = "okai-float-panel";'),
            ("assets/site.css", "#okai-floating-input.active { outline: 2px solid; }"),
        ):
            with self.subTest(relative=relative), self.assertRaisesRegex(SystemExit, "widget marker"):
                self.check(relative, contents)

    def test_allows_other_ok_ai_content(self):
        self.check("ai/chat-preview/index.html", """
            <h1>OK AI Chat UI Preview</h1>
            <button id="okai-float-panel-v2" class="okai-float okai-launch">Open</button>
            <script src="/assets/ok-ai-lite-preview-v2.js"></script>
        """)
