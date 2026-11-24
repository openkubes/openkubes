import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import byoh_guide as guide


class GuideProjectionTest(unittest.TestCase):
    def test_links_and_native_image_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / "docs").mkdir()
            (repo / "docs/installer.md").touch()
            (repo / "config").mkdir()
            source = (
                "[Local](01-introduction.md) "
                "[Installer](../installer.md#default) "
                "[Config](../../config) "
                "![Diagram](images/networking.svg) "
                "[External](https://kubernetes.io/)"
            )
            result = guide.project_markdown(source, repo)
            self.assertIn("[Local](01-introduction.md)", result)
            self.assertIn(f"{guide.REPO}/blob/{guide.PIN}/docs/installer.md#default", result)
            self.assertIn(f"{guide.REPO}/tree/{guide.PIN}/config", result)
            self.assertIn("[![Diagram](images/networking.svg)](images/networking.svg)", result)
            self.assertIn("[External](https://kubernetes.io/)", result)

    def test_missing_and_escaping_reference_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            for target in ("../missing.md", "../../../outside.md"):
                with self.subTest(target=target), self.assertRaises(SystemExit):
                    guide.project_markdown(f"[bad]({target})", repo)

    def test_expected_inventory(self):
        self.assertEqual(len(set(guide.CHAPTERS)), 12)
        self.assertEqual(len(set(guide.DIAGRAMS)), 13)
