import copy
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_happy_resume_v5_test", HERE / "bounded_happy_run_resume_v5.py")
RESUME = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RESUME
assert SPEC.loader is not None
SPEC.loader.exec_module(RESUME)


class HappyRunResumeV5Tests(unittest.TestCase):
    def test_candidate_is_inert_and_binds_status_semantics(self):
        candidate = RESUME.validate_candidate()
        self.assertEqual(candidate["spec"]["authorization"]["decision"], "NO-GO")
        self.assertEqual(candidate["spec"]["networkStatusSemantics"]["candidateDigest"], RESUME.STATUS_DIGEST)
        self.assertFalse(candidate["spec"]["identityImpact"]["fixtureDigestChanged"])

    def test_adapted_candidate_uses_new_exclusive_output(self):
        original = {"spec": {"observation": {"outputPath": "old"}}}
        base = lambda value: copy.deepcopy(value)
        amended = base(original)
        amended["spec"]["observation"]["outputPath"] = str(RESUME.NEW_NETWORK_OUTPUT)
        self.assertNotEqual(original["spec"]["observation"]["outputPath"], amended["spec"]["observation"]["outputPath"])

    def test_latest_evidence_validation_rejects_nonzero_probe_or_wrong_path_count(self):
        latest = {
            "kind": "GO1LNetworkReadyEvidence", "closureState": "FAIL-FUNCTIONAL-CONNECTIVITY", "NetworkReady": False,
            "fixedPodExecProbePerformed": True, "persistentMutationPerformed": False,
            "workloadTargetIdentityDigest": "sha256:" + "1" * 64,
            "details": {"probePod": {"name": "cilium-x", "uid": "uid-x"}},
        }
        diagnostic = {
            "kind": "GO1NetworkFunctionalDiagnosticEvidence", "probeExitCode": 0,
            "failedNetworkEvidenceDigest": "FILL", "podIdentityVerified": True,
            "probePod": latest["details"]["probePod"], "persistentMutationPerformed": False,
            "happyRunResumed": False, "rawProbeOutputRetained": False,
            "secretPayloadRetained": False, "workloadKubeconfigRemoved": True,
            "details": {"pathCount": 7, "paths": []},
        }
        with tempfile.TemporaryDirectory() as directory:
            latest_path = Path(directory) / "latest.json"
            diagnostic_path = Path(directory) / "diagnostic.json"
            for path, value in ((latest_path, latest), (diagnostic_path, diagnostic)):
                path.write_text(json.dumps(value))
                os.chmod(path, 0o600)
            spec = {
                "latestFailedNetworkEvidence": {"path": str(latest_path), "digest": RESUME.sha(latest_path)},
                "functionalDiagnosticEvidence": {"path": str(diagnostic_path), "digest": RESUME.sha(diagnostic_path)},
            }
            with mock.patch.object(RESUME, "LATEST_FAILED_PATH", latest_path), mock.patch.object(RESUME, "DIAGNOSTIC_PATH", diagnostic_path):
                with self.assertRaises(RESUME.ResumeV5Error):
                    RESUME.validate_latest_evidence(spec)

    def test_status_amendment_accepts_omission_but_rejects_null(self):
        self.assertTrue(RESUME.STATUS.successful_status({"lastProbed": "2026-08-14T15:30:00Z"}))
        self.assertFalse(RESUME.STATUS.successful_status({"status": None, "lastProbed": "2026-08-14T15:30:00Z"}))

    def test_template_remains_no_go(self):
        value = yaml.safe_load((HERE / "happy-run-resume-grant-v5.template.yaml").read_text())
        self.assertEqual(value["spec"]["decision"], "NO-GO")
        self.assertTrue(all(not item for key, item in value["spec"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()

