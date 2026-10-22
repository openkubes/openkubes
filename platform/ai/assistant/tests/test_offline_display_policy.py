"""Conservative offline candidate classification; never a render gate."""
import hashlib
import unittest

from public_beta.source_bound_command_reference import build_command_references
from public_beta.offline_display_policy import classify_display_candidate

R = "openkubes/ok-local"
P = "docs/tutorial-basic.md"
S = "a" * 40
SID = hashlib.sha256(f"{R}:{S}:{P}:0".encode()).hexdigest()[:16]


def snapshot(code):
    text = "```bash\n" + code + "\n```\n"
    return {"schema_version": 1, "corpus": [{
        "source_id": SID, "repo": R, "path": P, "revision": S,
        "chunk_number": 0, "text": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "url": f"https://github.com/{R}/blob/{S}/{P}",
    }]}


def classify(code):
    idx = snapshot(code)
    return classify_display_candidate(idx, build_command_references(idx)[0])


class OfflinePolicyTests(unittest.TestCase):
    def test_known_readonly(self):
        for cmd in ("kubectl get nodes", "kubectl get vm -w",
                    "clusterctl version", "virtctl version --client"):
            with self.subTest(cmd=cmd):
                result = classify(cmd)
                self.assertEqual(result["triage"], "low_risk_candidate")
                self.assertFalse(result["display_allowed"])

    def test_comments_remain_nonexecutable(self):
        self.assertEqual(classify("kubectl get nodes\n# NAME STATUS")["triage"], "low_risk_candidate")

    def test_unknown_wrapper_denied(self):
        for cmd in ("oml", "make verify", "brew install multipass", "sudo kubectl get nodes"):
            with self.subTest(cmd=cmd):
                self.assertEqual(classify(cmd)["triage"], "needs_manual_review")

    def test_shell_injection_denied(self):
        for cmd in ("kubectl get nodes; echo bad", "kubectl get nodes | cat",
                    "kubectl get nodes && whoami", "kubectl get nodes\nrm -rf tmp",
                    "kubectl get nodes $(whoami)", "kubectl get nodes > out"):
            with self.subTest(cmd=cmd):
                self.assertEqual(classify(cmd)["triage"], "needs_manual_review")

    def test_comment_only_denied(self):
        self.assertEqual(classify("# just an example")["triage"], "needs_manual_review")

    def test_multiple_version_checks(self):
        self.assertEqual(classify("clusterctl version   # v1.12+\nvirtctl version --client")["triage"], "low_risk_candidate")


    def test_readonly_continuation(self):
        command = "kubectl get kubevirt kubevirt -n kubevirt " + "\\" + "\n  -o jsonpath='{.spec.configuration.developerConfiguration}'"
        self.assertEqual(classify(command)["triage"], "low_risk_candidate")

    def test_inline_comment_and_injection(self):
        self.assertEqual(classify("clusterctl version   # v1.12+")["triage"], "low_risk_candidate")
        for command in ("clusterctl version # x", "kubectl get nodes  # x",
                        "clusterctl version  # x\nwhoami",
                        "clusterctl version  # x; echo hi\nwhoami"):
            with self.subTest(command=command):
                self.assertEqual(classify(command)["triage"], "needs_manual_review")

    def test_unsafe_continuation(self):
        for suffix in ("; whoami", "--raw=/api", "$(whoami)"):
            command = "kubectl get nodes " + "\\" + "\n  " + suffix
            with self.subTest(command=command):
                self.assertEqual(classify(command)["triage"], "needs_manual_review")

    def test_tampered_reference_rejected(self):
        idx = snapshot("kubectl get nodes")
        ref = build_command_references(idx)[0]
        ref["block_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            classify_display_candidate(idx, ref)


if __name__ == "__main__":
    unittest.main()
