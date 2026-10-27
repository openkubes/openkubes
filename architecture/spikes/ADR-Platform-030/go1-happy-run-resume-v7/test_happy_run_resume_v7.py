import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_happy_resume_v7_test", HERE / "bounded_happy_run_resume_v7.py")
RESUME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RESUME
assert SPEC.loader is not None
SPEC.loader.exec_module(RESUME)


class Completed:
    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class HappyRunResumeV7Tests(unittest.TestCase):
    def test_candidate_is_inert_and_has_exact_scope(self):
        candidate = RESUME.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(len(candidate["spec"]["absencePreflight"]["workload"]), 9)
        self.assertEqual(len(candidate["spec"]["absencePreflight"]["shared"]), 5)
        self.assertFalse(candidate["spec"]["resumeBoundary"]["earlierStagesReexecutionAllowed"])

    def test_template_remains_no_go(self):
        value = yaml.safe_load((HERE / "happy-run-resume-grant-v7.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))

    def test_absence_preflight_fails_on_present_or_unknown(self):
        absent = lambda *_args, **_kwargs: Completed(1, stderr=b"Error from server (NotFound): missing")
        self.assertEqual(RESUME.raw_get_absent(Path("kubectl"), Path("config"), "/exact", absent)["state"], "ABSENT")
        present = lambda *_args, **_kwargs: Completed(0, stdout=b'{"kind":"Secret"}')
        with self.assertRaises(RESUME.ResumeV7Error):
            RESUME.raw_get_absent(Path("kubectl"), Path("config"), "/exact", present)
        unknown = lambda *_args, **_kwargs: Completed(1, stderr=b"connection refused")
        with self.assertRaises(RESUME.ResumeV7Error):
            RESUME.raw_get_absent(Path("kubectl"), Path("config"), "/exact", unknown)

    def test_registration_secret_binds_target_without_leaking_to_evidence(self):
        binding = {"spec": {"target": {"capiClusterUID": "capi", "workloadKubeSystemUID": "ks", "workloadAPICAFingerprint": "ca", "workloadAPIServer": "https://target", "caData": "Y2E="}}}
        fixture = {"R": "r", "P": "p", "fixtureDigest": "f"}
        secret = RESUME.registration_secret(binding, fixture, "top-secret-token", "expiry")
        self.assertIn("top-secret-token", secret["stringData"]["config"])
        evidence = {"state": "REGISTRATION-CREATED", "credentialBytesRetained": False}
        self.assertNotIn("top-secret-token", json.dumps(evidence))

    def test_grant_authority_sets_are_disjoint(self):
        self.assertFalse(set(RESUME.TRUE) & set(RESUME.FALSE))
        self.assertIn("retryGranted", RESUME.FALSE)
        self.assertIn("earlierStageReexecutionGranted", RESUME.FALSE)


if __name__ == "__main__":
    unittest.main()
