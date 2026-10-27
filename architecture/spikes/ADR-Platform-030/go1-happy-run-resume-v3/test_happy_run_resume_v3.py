import copy
import importlib.util
import sys
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_resume_v3_test", HERE / "bounded_happy_run_resume_v3.py")
RUN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUN
assert SPEC.loader is not None
SPEC.loader.exec_module(RUN)


class ResumeV3Tests(unittest.TestCase):
    def test_candidate_is_inert_and_starts_after_g3(self):
        candidate = RUN.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(candidate["spec"]["resumeBoundary"]["nextStage"], "NETWORK")
        self.assertFalse(candidate["spec"]["resumeBoundary"]["g3ReexecutionAllowed"])

    def test_network_candidate_changes_only_output(self):
        original = RUN.HAPPY.NETWORK.validate_candidate(RUN.HAPPY.NETWORK.CANDIDATE)
        amended = RUN.amended_network_candidate(original)
        self.assertEqual(amended["spec"]["observation"]["outputPath"], str(RUN.NETWORK_OUTPUT_PATH))
        restored = copy.deepcopy(amended)
        restored["spec"]["observation"]["outputPath"] = original["spec"]["observation"]["outputPath"]
        self.assertEqual(restored, original)

    def test_bound_default_accepts_false_but_not_true(self):
        desired = yaml.safe_load((RUN.SPIKE / "go1-l-hcp-v1" / "helmchartproxy-phase-r-v5-candidate.yaml").read_text())
        observed = copy.deepcopy(desired)
        observed["spec"]["options"]["enableClientCache"] = False
        self.assertTrue(RUN.DEFAULTING.equivalent(desired, observed))
        observed["spec"]["options"]["enableClientCache"] = True
        self.assertFalse(RUN.DEFAULTING.equivalent(desired, observed))

    def test_prior_chain_accepts_only_expected_failure_boundary(self):
        lifecycle = {"kind": "GO1LLifecycleAPIEvidence", "closureState": "PASS-CURRENT-LIFECYCLE-API-EVIDENCE"}
        lifecycle_digest = "sha256:" + RUN.hashlib.sha256((RUN.json.dumps(lifecycle, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
        g3 = {"kind": "GO1LOperationEvidence", "spec": {"operation": "helmchartproxy", "semanticDigest": "sha256:cd1a21b0b611a3a928e6e7d63d7eb2c4b4657570152ac3c6ae6061a48d4b788e", "retryPerformed": False, "rollbackOrCleanupPerformed": False, "predecessorEvidenceDigests": [lifecycle_digest]}}
        failed = {"kind": "GO1LNetworkReadyEvidence", "closureState": "FAIL-HCP-SPEC", "NetworkReady": False, "candidateDigest": "sha256:15b24bd0d7247e0a05d4b1f291221cc52e4f1cefa498b8fe4c5d00b6347f3e04", "lifecycleEvidenceDigest": lifecycle_digest, "persistentMutationPerformed": False}
        RUN.validate_prior_values(lifecycle, g3, failed)
        failed["closureState"] = "WAIT-HCP-READY"
        with self.assertRaises(RUN.ResumeV3Error):
            RUN.validate_prior_values(lifecycle, g3, failed)

    def test_grant_template_is_no_go(self):
        template = yaml.safe_load((HERE / "happy-run-resume-grant-v3.template.yaml").read_text())
        self.assertEqual(template["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in template["spec"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
