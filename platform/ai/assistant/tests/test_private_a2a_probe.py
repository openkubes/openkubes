import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_beta.private_a2a_probe import extract_answer, run_probe

REV = "a" * 40
REPO = "openkubes/ok-local"
PATH = "docs/tutorial-basic.md"
URL = f"https://github.com/{REPO}/blob/{REV}/{PATH}"
FENCE = chr(96) * 3
TEXT = "Install on the Ubuntu VM.\n\n" + FENCE + "bash\nssh ubuntu@$VM_IP 'echo hello'\n" + FENCE
SOURCE_ID = hashlib.sha256(f"{REPO}:{REV}:{PATH}:0".encode()).hexdigest()[:16]


def fixture():
    return {"schema_version": 1, "corpus": [{
        "source_id": SOURCE_ID, "repo": REPO, "path": PATH,
        "revision": REV, "chunk_number": 0, "section": "Install",
        "url": URL, "sha256": hashlib.sha256(TEXT.encode()).hexdigest(),
        "text": TEXT,
    }]}


def a2a(text):
    return {"jsonrpc": "2.0", "result": {
        "kind": "task", "status": {"state": "completed"},
        "artifacts": [{"parts": [{"kind": "text", "text": text}]}],
    }}


class PrivateA2AProbeTests(unittest.TestCase):
    def test_extracts_completed_task_artifact(self):
        self.assertEqual(extract_answer(a2a("A response")), "A response")

    def test_rejects_incomplete_task(self):
        payload = a2a("Answer")
        payload["result"]["status"]["state"] = "working"
        with self.assertRaises(ValueError):
            extract_answer(payload)

    def test_rejects_json_rpc_error(self):
        with self.assertRaises(ValueError):
            extract_answer({"jsonrpc": "2.0", "error": {"code": -32600}})

    def test_accepts_source_only_static_answer(self):
        answer = f"Read [original documentation]({URL})"
        result = run_probe(fixture(), "Install ok-local",
                           ask=lambda question: answer)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["status"], "PASS")

    def test_rejects_invented_command(self):
        answer = "Run this:\n\n" + FENCE + f"bash\nsudo rm -rf /\n" + FENCE + f"\n[Source]({URL})"
        result = run_probe(fixture(), "Install ok-local",
                           ask=lambda question: answer)
        self.assertFalse(result["accepted"])
        self.assertIn("unverified_shell_block", result["reasons"])

    def test_rejects_bare_source_id(self):
        result = run_probe(fixture(), "Install ok-local",
                           ask=lambda question: f"source_id={SOURCE_ID}")
        self.assertFalse(result["accepted"])

    def test_does_not_invoke_agent_when_no_sources(self):
        def should_not_run(question):
            raise AssertionError("Agent invoked without sources")
        result = run_probe(fixture(), "zzzzunmatched",
                           ask=should_not_run)
        self.assertEqual(result["status"], "NO_SOURCES")


if __name__ == "__main__":
    unittest.main()
