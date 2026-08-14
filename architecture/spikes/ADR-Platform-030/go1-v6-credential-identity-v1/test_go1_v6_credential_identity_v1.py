from __future__ import annotations

import datetime as dt
import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_go1_v6_credential_identity", HERE / "inspect_go1_v6_credentials_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CredentialIdentityTests(unittest.TestCase):
    def test_candidate_and_plan_are_inert(self):
        candidate = MODULE.validate_candidate()
        result = MODULE.plan()
        self.assertEqual(candidate["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO")
        self.assertEqual(result["scope"], ["ok-infra", "ok-mgmt", "ok-shared"])
        self.assertFalse(result["credentialInspectionGranted"])
        self.assertFalse(result["clusterContacted"])
        self.assertFalse(result["mutationAuthorized"])

    def test_long_grant_window_fails_closed(self):
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1V6CredentialIdentityGrant",
            "spec": {
                "decision": "GO", "candidateDigest": MODULE.sha(MODULE.CANDIDATE),
                "scope": "inspect-three-local-kubeconfig-identities", "grantID": "test", "singleRun": True,
                "credentialInspectionGranted": True, "clusterContactGranted": False, "mutationAuthorized": False,
                "issuedAt": "2026-08-14T10:00:00Z", "expiresAt": "2026-08-14T10:16:00Z",
            },
        }
        with self.assertRaises(MODULE.InspectionError):
            MODULE.validate_grant(MODULE.CANDIDATE, grant, dt.datetime(2026, 8, 14, 10, 1, tzinfo=dt.timezone.utc))

    def test_evidence_write_is_exclusive(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence.json"
            MODULE.write_exclusive(target, {"ok": True})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_exclusive(target, {"ok": False})

    def test_grant_preflight_is_unresolved_and_non_authorizing(self):
        value = yaml.safe_load((HERE / "credential-identity-grant-preflight-v1.yaml").read_text())["spec"]
        self.assertEqual(value["sourceCandidate"]["digest"], MODULE.sha(MODULE.CANDIDATE))
        self.assertEqual(value["requestedAuthority"]["windowStart"], "UNRESOLVED")
        self.assertEqual(value["requestedAuthority"]["windowEnd"], "UNRESOLVED")
        self.assertEqual(value["authorization"]["decision"], "NO-GO")
        self.assertFalse(any(v for k, v in value["authorization"].items() if k.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
