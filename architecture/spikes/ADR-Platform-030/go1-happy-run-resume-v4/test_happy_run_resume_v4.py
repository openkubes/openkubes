import copy
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_resume_v4_test", HERE / "bounded_happy_run_resume_v4.py")
RUN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUN
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN)


class ResumeV4Tests(unittest.TestCase):
    def test_candidate_is_inert_and_requires_present_g3(self):
        candidate = RUN.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        amendment = candidate["spec"]["validatorAmendment"]
        self.assertEqual(amendment["resumeRule"], "EXACT-BOUND-G3-EVIDENCE-MUST-BE-PRESENT")
        self.assertFalse(amendment["g3ReexecutionAllowed"])

    def test_pre_g3_values_accept_preserved_chain(self):
        run_id = "ok141-go1-l-test"
        preflight = {"kind": "GO1V6PreflightEvidence", "spec": {"result": "PASS-FRESH-BASELINE-AND-PREREQUISITES", "mutationPerformed": False}}
        digests = {name: "sha256:" + str(index) * 64 for index, name in enumerate(RUN.OPERATIONS, start=1)}
        summary = {"kind": "GO1LStageEvidence", "spec": {"stage": "G1", "result": "SUBMITTED-STOP-PRESERVE", "runID": run_id, "mutationCount": 12, "retryPerformed": False, "rollbackOrCleanupPerformed": False, "operationEvidenceDigests": digests}}
        operations = {name: {"kind": "GO1LOperationEvidence", "spec": {"operation": name, "runID": run_id, "retryPerformed": False, "rollbackOrCleanupPerformed": False}} for name in RUN.OPERATIONS}
        RUN.validate_pre_g3_values(preflight, summary, operations, run_id)
        summary["spec"]["mutationCount"] = 11
        with self.assertRaises(RUN.ResumeV4Error):
            RUN.validate_pre_g3_values(preflight, summary, operations, run_id)

    def test_adaptation_preserves_no_g3_authority(self):
        grant = {"kind": "GO1HappyRunResumeGrantV4", "spec": {"candidateDigest": "new", "g3Granted": False}}
        adapted = RUN.adapt_grant(grant)
        self.assertEqual(adapted["kind"], "GO1HappyRunResumeGrantV3")
        self.assertEqual(adapted["spec"]["candidateDigest"], RUN.V3_DIGEST)
        self.assertFalse(adapted["spec"]["g3Granted"])
        self.assertEqual(grant["kind"], "GO1HappyRunResumeGrantV4")

    def test_v3_candidate_remains_unchanged(self):
        self.assertEqual(RUN.sha(RUN.V3_CANDIDATE), RUN.V3_DIGEST)

    def test_grant_template_is_no_go(self):
        template = yaml.safe_load((HERE / "happy-run-resume-grant-v4.template.yaml").read_text())
        self.assertEqual(template["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in template["spec"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
