"""Offline-only tests; never calls a live controller or model."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docs_mcp import DocsRetriever
from public_beta.private_semantic_review import (
    capture_private_review, _write_private_new_file,
)
from test_private_context_gateway_probe import fixture


class PrivateSemanticReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "private"
        self.folder.mkdir(mode=0o700)
        self.index = fixture()

    def _synthetic_valid_sender(self, encoded):
        context = json.loads(encoded)
        sid = context["sources"][0]["source_id"]
        return json.dumps({"version": "0.1", "steps": [
            {"text": "Read the installation overview.", "source_ids": [sid]}
        ]})

    def test_accepted_packet_is_local_and_pending(self):
        result = capture_private_review(
            self.index, "definition-ok-local", self.folder,
            send=self._synthetic_valid_sender)
        self.assertEqual(result["status"], "CAPTURED_PRIVATE")
        self.assertEqual(result["semantic_grounding"], "UNVERIFIED")
        self.assertNotIn("rendered_answer", result)
        self.assertNotIn("snippet", str(result))
        files = list(self.folder.iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        packet = json.loads(files[0].read_text())
        self.assertEqual(packet["review_decision"], "PENDING_HUMAN_REVIEW")
        self.assertEqual(packet["semantic_grounding"], "UNVERIFIED")
        self.assertEqual(packet["rendered_answer"].split(" [Source")[0],
                         "1. Read the installation overview.")
        self.assertEqual(packet["sources_used"][0]["exact_retrieved_snippet"],
                         self.index["corpus"][0]["text"])

    def test_rejected_answer_not_saved(self):
        def sender(_):
            return "secret-invalid-model-output"
        result = capture_private_review(
            self.index, "definition-ok-local", self.folder, send=sender)
        self.assertEqual(result["status"], "REJECT")
        self.assertFalse(list(self.folder.iterdir()))
        self.assertNotIn("secret", str(result))

    def test_command_answer_never_saved(self):
        def sender(encoded):
            sid = json.loads(encoded)["sources"][0]["source_id"]
            return json.dumps({"version": "0.1", "steps": [
                {"text": "Run kubectl get pods.", "source_ids": [sid]}]})
        result = capture_private_review(
            self.index, "install-macos", self.folder, send=sender)
        self.assertEqual(result["status"], "REJECT")
        self.assertFalse(list(self.folder.iterdir()))

    def test_private_directory_required(self):
        self.folder.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "review_dir_not_private"):
            capture_private_review(
                self.index, "definition-ok-local", self.folder,
                send=lambda _: self.fail("must not send"))

    def test_preexisting_file_never_overwritten(self):
        file = self.folder / "review.json"
        file.write_text("original")
        with self.assertRaises(FileExistsError):
            _write_private_new_file(file, b"new")
        self.assertEqual(file.read_text(), "original")

    def test_unknown_case_does_not_send(self):
        with self.assertRaisesRegex(ValueError, "unknown_review_case"):
            capture_private_review(
                self.index, "unexpected-case-id", self.folder,
                send=lambda _: self.fail("must not send"))

    def test_symlink_directory_rejected(self):
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.folder, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "review_dir_symlink"):
            capture_private_review(
                self.index, "definition-ok-local", link,
                send=lambda _: self.fail("must not send"))


if __name__ == "__main__":
    unittest.main()
