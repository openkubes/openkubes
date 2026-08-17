from __future__ import annotations

import datetime as dt
import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_go1_v6_preflight_v2", HERE / "bounded_go1_v6_preflight_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class GO1V6PreflightV2Tests(unittest.TestCase):
    def test_candidate_and_plan_bind_exact_client(self):
        candidate, _, closure = MODULE.validate_candidate()
        plan = MODULE.plan()
        self.assertEqual(candidate["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO")
        self.assertEqual(plan["queryCount"], 17)
        self.assertEqual(plan["logicalAbsenceClaimCount"], 13)
        self.assertTrue(all(item["command"][0] == str(MODULE.CLIENT_PATH) for item in plan["queries"]))
        self.assertEqual(set(closure["spec"]["identities"]), {"ok-infra", "ok-mgmt", "ok-shared"})
        self.assertFalse(plan["credentialUseGranted"])
        self.assertFalse(plan["clusterContacted"])
        self.assertFalse(plan["mutationAuthorized"])

    def test_local_client_matches_binding(self):
        result = MODULE.verify_client()
        self.assertEqual(result["digest"], MODULE.CLIENT_DIGEST)
        self.assertEqual(result["version"], "v1.34.1")
        self.assertEqual(result["platform"], "darwin/amd64")

    def test_long_grant_window_fails(self):
        identities = {plane: values for plane, values in MODULE.validate_candidate()[2]["spec"]["identities"].items()}
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1V6PreflightGrantV2",
            "spec": {
                "decision": "GO", "candidateDigest": MODULE.sha(MODULE.CANDIDATE),
                "protocolDigest": MODULE.V1.EXPECTED_PROTOCOL_DIGEST, "clientDigest": MODULE.CLIENT_DIGEST,
                "expectedCredentialIdentities": identities, "grantID": "test", "singleRun": True,
                "readOnly": True, "mutationAuthorized": False,
                "issuedAt": "2026-08-14T10:00:00Z", "expiresAt": "2026-08-14T10:16:00Z",
            },
        }
        with self.assertRaises(MODULE.PreflightV2Error):
            MODULE.validate_grant(MODULE.CANDIDATE, grant, identities, dt.datetime(2026, 8, 14, 10, 1, tzinfo=dt.timezone.utc))


if __name__ == "__main__":
    unittest.main()
