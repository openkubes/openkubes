"""Offline privacy and structural regression tests for diagnostics v2."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_beta.answer_diagnostics import format_diagnostics_v2

F = chr(96) * 3
URL = "https://github.com/openkubes/ok-local/blob/" + "a" * 40 + "/docs/tutorial-basic.md"
HITS = {"results": [{"url": URL, "snippet": "safe content"}]}


class FormatDiagnosticsV2Tests(unittest.TestCase):
    def test_standalone_fences_and_safe_language_bucket(self):
        answer = F + "javascript PRIVATE-SECRET\nconsole.log(123)\n" + F + "\n" + F + "bash\necho hello\n" + F
        report = format_diagnostics_v2(answer, HITS)
        self.assertEqual(report["fence_languages"]["other"], 1)
        self.assertEqual(report["fence_languages"]["bash"], 1)
        self.assertEqual(report["standalone_fence_line_numbers"], [1, 3, 4, 6])
        self.assertFalse(report["unmatched_standalone_fence"])
        self.assertNotIn("PRIVATE-SECRET", str(report))
        self.assertNotIn("console.log", str(report))

    def test_rejects_fence_embedded_in_table_as_structure_only(self):
        answer = "| Step | " + F + "bash |\nexample"
        report = format_diagnostics_v2(answer, HITS)
        self.assertEqual(report["embedded_fence_marker_count"], 1)
        self.assertEqual(report["standalone_fence_line_count"], 0)
        self.assertNotIn("example", str(report))

    def test_unmatched_fence(self):
        report = format_diagnostics_v2(F + "json\n{SECRET}", HITS)
        self.assertTrue(report["unmatched_standalone_fence"])
        self.assertEqual(report["fence_languages"]["json"], 1)
        self.assertNotIn("SECRET", str(report))

    def test_url_classes_and_inline_markup_are_redacted(self):
        answer = (
            "[Trusted](" + URL + ") "
            + "https://github.com/other/PRIVATE "
            + "https://example.net/SECRET "
            + "http://private.example/SECRET "
            + chr(96) + "TOKEN" + chr(96) + " <PRIVATE>"
        )
        report = format_diagnostics_v2(answer, HITS)
        self.assertEqual(report["markdown_link_count"], 1)
        self.assertEqual(report["trusted_markdown_link_count"], 1)
        self.assertEqual(report["bare_url_classes"], {
            "github_https": 1, "other_https": 1, "http": 1
        })
        self.assertEqual(report["inline_single_backtick_count_outside_recognized_fences"], 2)
        self.assertEqual(report["angle_bracket_count_outside_recognized_fences"], 2)
        for secret in ("PRIVATE", "SECRET", "TOKEN", URL, "example.net"):
            self.assertNotIn(secret, str(report))

    def test_bounds_and_invalid_retrieval(self):
        for answer, hits in ((None, HITS), ("a" * 20_001, HITS), ("hi", {})):
            with self.subTest(answer_type=type(answer).__name__):
                with self.assertRaises(ValueError):
                    format_diagnostics_v2(answer, hits)


if __name__ == "__main__":
    unittest.main()
