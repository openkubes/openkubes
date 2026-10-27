import datetime as dt
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("resume", HERE / "bounded_happy_run_resume_v1.py")
resume = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resume)


class ResumeTests(unittest.TestCase):
    def test_candidate_is_no_go(self):
        plan = resume.plan()
        self.assertEqual(plan["authorization"], "NO-GO")
        self.assertFalse(plan["resumeBoundary"]["preflightReexecutionAllowed"])
        self.assertFalse(plan["resumeBoundary"]["g1ReexecutionAllowed"])

    def test_lifecycle_grant_gets_both_missing_immutable_bindings(self):
        candidate = resume.V2.V1.LIFECYCLE.validate_candidate(resume.V2.V1.LIFECYCLE.CANDIDATE)["spec"]
        value = {"spec": {}}
        amended = resume.amend_generated_grant("lifecycle", value, {})
        self.assertEqual(amended["spec"]["runtimePackageDigest"], candidate["runtimePackage"]["digest"])
        self.assertEqual(amended["spec"]["credentialIdentityDigest"], candidate["credential"]["identityDigest"])

    def test_g1_is_downgraded_to_resume_only_and_g3_reuses_prior_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "g1-summary.json"
            summary.write_text("{}")
            resume_state = {"summary": summary, "summaryValue": {"runID": "ok141-go1-l-existing"}}
            g1 = resume.amend_generated_grant("g1", {"spec": {"g1Granted": True}}, resume_state)
            self.assertFalse(g1["spec"]["g1Granted"])
            self.assertTrue(g1["spec"]["resumeFromG1Granted"])
            g3 = resume.amend_generated_grant("g3", {"spec": {"runID": "wrong"}}, resume_state)
            self.assertEqual(g3["spec"]["runID"], "ok141-go1-l-existing")

    def test_safe_file_rejects_wrong_digest(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("{}")
            path = Path(handle.name)
        try:
            os.chmod(path, 0o600)
            with self.assertRaises(resume.ResumeError):
                resume.safe_file(path, "sha256:" + "0" * 64, "fixture")
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
