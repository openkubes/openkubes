"""Offline contract checks for preview-only static curated Lite widget."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_beta.curated_lite import QUESTIONS, REQUIRED_QUOTE

SCRIPT = ROOT / "website/assets/ok-ai-lite-preview.js"
OVERRIDE = ROOT / "website/overrides/main.html"


class LiteStaticPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = SCRIPT.read_text(encoding="utf-8")
        cls.override = OVERRIDE.read_text(encoding="utf-8")

    def test_preview_host_is_only_allowed_host(self):
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', self.script)
        self.assertIn('window.location.hostname !== "preview.openkubes.org"', self.override)

    def test_only_static_curated_answers_are_used(self):
        for question, answer in QUESTIONS.items():
            with self.subTest(question=question):
                self.assertIn('"' + question + '"', self.script)
                self.assertIn(answer, self.script)
        self.assertIn("No AI backend", self.script)

    def test_source_uses_known_pinned_commit(self):
        self.assertIn(
            "60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e/docs/tutorial-basic.md",
            self.script)
        self.assertIn("fully automated local dev environment", REQUIRED_QUOTE)
        self.assertNotIn("mirrors production Kubernetes", self.script)
        self.assertNotIn("single-node Kubernetes setup", self.script)

    def test_no_network_api_calls_or_client_secrets(self):
        for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket(",
                       "Authorization:", "Bearer ", "OPENKUBES_BETA1_LITE_TOKEN",
                       "localhost:8765", "kagent-controller"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, self.script)

    def test_preview_override_includes_lite_not_old_demo(self):
        self.assertIn("assets/ok-ai-lite-preview.js", self.override)
        self.assertNotIn("assets/ok-ai-floating-demo.js", self.override)

    def test_fail_closed_allowlist_and_text_only_output(self):
        self.assertIn("hasOwnProperty.call(supported, key)", self.script)
        self.assertIn('el.textContent = value', self.script)
        self.assertIn("Unsupported", self.script.replace("unsupported", "Unsupported"))
        self.assertIn('a.rel = "noopener noreferrer"', self.script)


if __name__ == "__main__":
    unittest.main()
