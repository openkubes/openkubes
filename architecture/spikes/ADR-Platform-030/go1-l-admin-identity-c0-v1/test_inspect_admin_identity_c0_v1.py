import copy
import datetime as dt
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("admin_identity_c0_test", HERE / "inspect_admin_identity_c0_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AdminIdentityC0Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-l-admin-identity-c0-candidate-v1.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 13, 16, 0, tzinfo=dt.timezone.utc)

    def grant(self):
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "LocalCredentialInspectionGrant",
            "spec": {
                "decision": "GO",
                "credentialInspectionGranted": True,
                "clusterContactGranted": False,
                "mutationAuthorized": False,
                "candidateDigest": MODULE.sha(self.path),
                "scope": "inspect-two-local-admin-kubeconfig-identities",
                "grantID": "ok141-c0-test-only",
                "singleRun": True,
                "issuedAt": "2026-08-13T15:58:00Z",
                "expiresAt": "2026-08-13T16:08:00Z",
            },
        }

    def assert_rejected(self, changed):
        with self.assertRaises((MODULE.InspectionError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(changed, self.path)

    def test_candidate_plan_is_non_authorizing(self):
        result = MODULE.plan(self.candidate, self.path)
        self.assertFalse(result["credentialInspectionGranted"])
        self.assertFalse(result["clusterContacted"])
        self.assertFalse(result["mutationAuthorized"])

    def test_source_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["sourceAcceptance"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_path_scope_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["credentialFiles"][0]["path"] = "/tmp/other"
        self.assert_rejected(changed)

    def test_identity_cannot_be_preclaimed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["credentialFiles"][0]["inspectionComplete"] = True
        self.assert_rejected(changed)

    def test_any_candidate_grant_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["credentialInspectionGranted"] = True
        self.assert_rejected(changed)

    def test_expired_or_mutating_runtime_grant_fails_closed(self):
        for mode in ("expired", "mutating"):
            grant = self.grant()
            if mode == "expired":
                grant["spec"]["expiresAt"] = "2026-08-13T15:59:00Z"
            else:
                grant["spec"]["mutationAuthorized"] = True
            with self.subTest(mode=mode), self.assertRaises(MODULE.InspectionError):
                MODULE.validate_grant(self.path, grant, self.now)

    def test_fake_identity_inspection_emits_only_redacted_fields(self):
        original = MODULE.PRE.inspect_kubeconfig
        MODULE.PRE.inspect_kubeconfig = lambda path: {
            "context": "forbidden-context",
            "cluster": "forbidden-cluster",
            "user": "forbidden-user",
            "server": "https://192.0.2.10:6443",
            "caFingerprint": "sha256:" + "1" * 64,
            "credentialIdentityDigest": "sha256:" + "2" * 64,
        }
        try:
            result = MODULE.inspect(self.candidate, self.path, self.grant(), self.now)
        finally:
            MODULE.PRE.inspect_kubeconfig = original
        self.assertEqual(len(result["identities"]), 2)
        self.assertTrue(all("context" not in item and "cluster" not in item and "user" not in item for item in result["identities"]))
        self.assertFalse(result["clusterContacted"])
        self.assertFalse(result["mutationPerformed"])

    def test_wrong_candidate_runtime_grant_fails_closed(self):
        grant = self.grant()
        grant["spec"]["candidateDigest"] = "sha256:" + "0" * 64
        with self.assertRaises(MODULE.InspectionError):
            MODULE.validate_grant(self.path, grant, self.now)


if __name__ == "__main__":
    unittest.main()
