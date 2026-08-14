import importlib.util
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_runtime_binding_resume_test", HERE / "bounded_runtime_binding_resume_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RuntimeBindingResumeTests(unittest.TestCase):
    def test_candidate_is_inert(self):
        candidate = MODULE.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertTrue(all(not value for key, value in candidate["spec"]["authorization"].items() if key.endswith("Granted")))

    def test_adapted_grant_never_grants_platform(self):
        outer = {"spec": {"authority": "github:arashkaffamanesh", "grantID": "test", "issuedAt": "2026-08-14T16:45:00Z", "expiresAt": "2026-08-14T17:00:00Z", "lifecycleEvidenceDigest": "sha256:" + "1" * 64, "networkReadyEvidenceDigest": "sha256:" + "2" * 64}}
        adapted = MODULE.adapted_grant(MODULE.CANDIDATE, outer)["spec"]
        self.assertFalse(adapted["persistentMutationGranted"])
        self.assertFalse(adapted["registrationGranted"])
        self.assertFalse(adapted["platformSubmissionGranted"])
        self.assertFalse(adapted["go1Granted"])


if __name__ == "__main__":
    unittest.main()
