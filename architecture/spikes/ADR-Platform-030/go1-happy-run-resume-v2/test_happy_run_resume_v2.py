import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("resume_v2", HERE / "bounded_happy_run_resume_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ResumeV2Tests(unittest.TestCase):
    def test_candidate_is_no_go_and_does_not_publish_private_digest(self):
        plan = MODULE.plan()
        self.assertEqual(plan["authorization"], "NO-GO")
        self.assertFalse(plan["clusterContacted"])
        self.assertFalse(plan["mutationPerformed"])
        self.assertFalse(plan["requiredRemediation"]["digestPublishedInCandidate"])

    def test_adaptation_preserves_authority_and_changes_only_wrapper_identity(self):
        grant = {"kind": "GO1HappyRunResumeGrantV2", "spec": {"candidateDigest": "outer", "g3Granted": True}}
        adapted = MODULE.adapt_grant(grant)
        self.assertEqual(adapted["kind"], "GO1HappyRunResumeGrant")
        self.assertEqual(adapted["spec"]["candidateDigest"], MODULE.V1_CANDIDATE_DIGEST)
        self.assertTrue(adapted["spec"]["g3Granted"])
        self.assertEqual(grant["spec"]["candidateDigest"], "outer")

    def test_private_evidence_is_fail_closed_and_secret_safe(self):
        value = {
            "apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "LBNamespaceRemediationEvidence",
            "spec": {
                "candidateDigest": MODULE.REMEDIATION_CANDIDATE_DIGEST,
                "result": "REMEDIATED-PRESERVE-HAPPY-RUN",
                "runID": "ok141-lb-namespace-remediation-test",
                "targetService": {"vip": "192.168.100.213", "endpointAddressCount": 1},
                "endpointsAfterTrigger": {"cluster": {"host": "192.168.100.213", "port": 6443}, "kubevirtCluster": {"host": "192.168.100.213", "port": 6443}},
                "secretBytesEmitted": False, "secretDigestEmitted": False, "retryPerformed": False,
                "rollbackOrGeneralCleanupPerformed": False, "happyRunResumed": False,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(value))
            os.chmod(path, 0o600)
            original = MODULE.REMEDIATION_EVIDENCE_PATH
            MODULE.REMEDIATION_EVIDENCE_PATH = path
            try:
                result = MODULE.safe_private_evidence(path, MODULE.sha(path))
                self.assertEqual(result["spec"]["result"], "REMEDIATED-PRESERVE-HAPPY-RUN")
                value["spec"]["targetService"]["vip"] = "192.168.100.214"
                path.write_text(json.dumps(value))
                with self.assertRaises(MODULE.ResumeV2Error):
                    MODULE.safe_private_evidence(path, MODULE.sha(path))
            finally:
                MODULE.REMEDIATION_EVIDENCE_PATH = original


if __name__ == "__main__":
    unittest.main()
