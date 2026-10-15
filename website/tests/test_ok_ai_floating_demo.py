"""Static regression guards for the preview-only OK AI dummy widget."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FloatingDemoTests(unittest.TestCase):
    def test_host_gate_in_template_and_runtime(self):
        template = (ROOT / "website/overrides/main.html").read_text()
        script = (ROOT / "website/assets/ok-ai-floating-demo.js").read_text()
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', template)
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', script)
        self.assertIn("ok-ai-floating-demo.js", template)

    def test_no_network_or_storage_access_in_dummy(self):
        script = (ROOT / "website/assets/ok-ai-floating-demo.js").read_text()
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "localStorage",
                          "sessionStorage", "sendBeacon(", "innerHTML = question"):
            self.assertNotIn(forbidden, script)
        self.assertIn("Demo only", script)

    def test_staging_includes_assets(self):
        staging = (ROOT / "website/scripts/stage-legacy.py").read_text()
        self.assertIn('"ok-ai-floating-demo.js"', staging)
        self.assertIn('"ok-ai-floating-demo.css"', staging)


if __name__ == "__main__":
    unittest.main()
