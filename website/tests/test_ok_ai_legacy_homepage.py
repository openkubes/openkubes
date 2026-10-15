"""Guard the legacy homepage preview-only OK AI widget injection."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]

class LegacyHomepageWidgetTests(unittest.TestCase):
    def test_homepage_loads_assets_only_on_preview(self):
        html = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', html)
        self.assertIn('"/assets/ok-ai-floating-demo.js"', html)
        self.assertIn('"/assets/ok-ai-floating-demo.css"', html)
        guard = html.index('window.location.hostname !== "preview.openkubes.org"')
        self.assertLess(guard, html.index('script.src = "/assets/ok-ai-floating-demo.js"'))
        self.assertLess(guard, html.index('css.href = "/assets/ok-ai-floating-demo.css"'))

    def test_assets_are_the_existing_preview_only_demo(self):
        script = (ROOT / "website/assets/ok-ai-floating-demo.js").read_text(encoding="utf-8")
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', script)
        self.assertIn("Demo only", script)
        self.assertNotIn("fetch(", script)


if __name__ == "__main__":
    unittest.main()
