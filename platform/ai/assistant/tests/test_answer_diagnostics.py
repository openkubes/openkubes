import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_beta.answer_diagnostics import diagnostic_counts

F = chr(96) * 3
URL = "https://github.com/openkubes/ok-local/blob/" + "a" * 40 + "/docs/tutorial-basic.md"
PASSAGE = F + "bash\necho permitted\n" + F
HITS = {"results": [{"url": URL, "snippet": PASSAGE}]}


class AnswerDiagnosticsTests(unittest.TestCase):
    def test_safe_counts_without_raw_answer(self):
        answer = F + "bash\necho permitted\n" + F + "\n" + f"[Source]({URL})"
        report = diagnostic_counts(answer, HITS)
        self.assertEqual(report["recognized_shell_fences"], 1)
        self.assertEqual(report["unverified_shell_fences"], 0)
        self.assertEqual(report["trusted_markdown_links"], 1)
        serialized = str(report)
        self.assertNotIn("echo permitted", serialized)
        self.assertNotIn(URL, serialized)

    def test_unverified_command_and_source_token(self):
        answer = F + "bash\nssh unknown\n" + F + "\nsource_id=" + "b" * 16
        report = diagnostic_counts(answer, HITS)
        self.assertEqual(report["unverified_shell_fences"], 1)
        self.assertEqual(report["bare_source_token_count"], 1)
        self.assertEqual(report["markdown_links"], 0)
        self.assertNotIn("ssh unknown", str(report))

    def test_inline_backtick_counts_without_echoing(self):
        answer = "Run " + chr(96) + "echo secret" + chr(96) + "."
        report = diagnostic_counts(answer, HITS)
        self.assertTrue(report["has_inline_backticks_outside_fences"])
        self.assertNotIn("secret", str(report))

    def test_classifies_fences_in_tables_without_exposing_content(self):
        answer = "| Step | Command |\n| --- | --- |\n| Install | " + F + "bash |\n| command |"
        report = diagnostic_counts(answer, HITS)
        self.assertEqual(report["fence_marker_count"], 1)
        self.assertEqual(report["table_embedded_fence_lines"], 1)
        self.assertEqual(report["recognized_shell_fences"], 0)
        self.assertNotIn("command", str(report))

    def test_classifies_standalone_and_list_embedded_fences(self):
        answer = F + "bash\n" + "echo permitted\n" + F + "\n- " + F + "bash\n"
        report = diagnostic_counts(answer, HITS)
        self.assertEqual(report["standalone_fence_lines"], 2)
        self.assertEqual(report["list_embedded_fence_lines"], 1)
        self.assertEqual(report["lines_containing_fences"], 3)

    def test_retrieval_limit_flag_is_only_structural(self):
        report = diagnostic_counts("Answer", {"results": HITS["results"] * 8})
        self.assertTrue(report["retrieval_at_limit"])
        self.assertFalse(diagnostic_counts("Answer", HITS)["retrieval_at_limit"])


if __name__ == "__main__":
    unittest.main()
