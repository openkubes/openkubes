"""Regression tests for keeping unpublished legal-review drafts out of Pages."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-github-pages-build.py"
spec = importlib.util.spec_from_file_location("pages_build_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)


class LegalDraftTests(unittest.TestCase):
    def test_unpublished_imprint_html_is_blocked(self):
        with TemporaryDirectory() as directory:
            page = Path(directory, "index.html")
            page.write_text("Entwurf: Impressum für openkubes.org (nicht veröffentlicht)", encoding="utf-8")
            with self.assertRaises(SystemExit):
                guard.check_unapproved_legal_drafts(Path(directory))

    def test_unpublished_privacy_html_is_blocked(self):
        with TemporaryDirectory() as directory:
            page = Path(directory, "privacy", "index.html")
            page.parent.mkdir()
            page.write_text("Entwurf: Datenschutzerklärung für openkubes.org (nicht veröffentlicht)", encoding="utf-8")
            with self.assertRaises(SystemExit):
                guard.check_unapproved_legal_drafts(Path(directory))

    def test_unpublished_markdown_is_blocked(self):
        with TemporaryDirectory() as directory:
            Path(directory, "PRIVACY-NOTICE-DRAFT-DE.md").write_text("draft", encoding="utf-8")
            with self.assertRaises(SystemExit):
                guard.check_unapproved_legal_drafts(Path(directory))

    def test_normal_website_is_allowed(self):
        with TemporaryDirectory() as directory:
            Path(directory, "index.html").write_text("<h1>OpenKubes</h1>", encoding="utf-8")
            guard.check_unapproved_legal_drafts(Path(directory))


if __name__ == "__main__":
    unittest.main()
