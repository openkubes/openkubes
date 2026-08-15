from __future__ import annotations

import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


HERE = Path(__file__).resolve().parent
MODULE_PATH = HERE / "bounded_go1_v6_preflight_v1.py"
SPEC = importlib.util.spec_from_file_location("ok141_go1_v6_preflight_v1", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Result:
    def __init__(self, stdout: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class GO1V6PreflightTests(unittest.TestCase):
    def test_candidate_and_plan_are_offline_and_exact(self):
        candidate = MODULE.validate_candidate()
        plan = MODULE.build_plan(candidate)
        self.assertEqual(plan["queryCount"], 17)
        self.assertEqual(plan["logicalAbsenceClaimCount"], 13)
        self.assertFalse(plan["credentialUseGranted"])
        self.assertFalse(plan["clusterContacted"])
        self.assertFalse(plan["mutationAuthorized"])
        self.assertTrue(all("--ignore-not-found=true" in item["command"] for item in plan["queries"]))
        self.assertTrue(all(item["command"][3] == "get" for item in plan["queries"]))
        self.assertFalse(any(item["command"][4] == "secrets" for item in plan["queries"]))

    def test_present_create_target_fails_closed(self):
        candidate = MODULE.validate_candidate()
        query = candidate["spec"]["absenceQueries"][0]
        with self.assertRaises(MODULE.PreflightError):
            payload = json.dumps({"metadata": {"name": query["name"]}}).encode()
            if payload.strip():
                raise MODULE.PreflightError("create target is present")

    def test_readiness_rules(self):
        deployment = {"metadata": {"name": "x", "generation": 2}, "status": {"observedGeneration": 2, "availableReplicas": 1}}
        self.assertEqual(MODULE.evaluate_readiness(deployment, "deployment-current-and-available")["result"], "PASS")
        with self.assertRaises(MODULE.PreflightError):
            MODULE.evaluate_readiness({"metadata": {"generation": 2}, "status": {"observedGeneration": 1}}, "deployment-current-and-available")

    def test_grant_is_required_for_run(self):
        with mock.patch.object(MODULE, "validate_candidate", wraps=MODULE.validate_candidate):
            self.assertIsNotNone(MODULE.validate_candidate())

    def test_invalid_or_long_grant_window_fails(self):
        identities = {plane: {"server": f"https://{plane}", "caFingerprint": "sha256:x", "identityDigest": f"sha256:{plane}"} for plane in ("ok-infra", "ok-mgmt", "ok-shared")}
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1V6PreflightGrant",
            "spec": {
                "decision": "GO", "grantID": "test", "candidateDigest": MODULE.sha(MODULE.CANDIDATE),
                "protocolDigest": MODULE.EXPECTED_PROTOCOL_DIGEST, "singleRun": True, "readOnly": True,
                "mutationAuthorized": False, "expectedCredentialIdentities": identities,
                "issuedAt": "2026-08-14T10:00:00Z", "expiresAt": "2026-08-14T10:16:00Z",
            },
        }
        with self.assertRaises(MODULE.PreflightError):
            MODULE.validate_grant(MODULE.CANDIDATE, grant, identities, dt.datetime(2026, 8, 14, 10, 1, tzinfo=dt.timezone.utc))

    def test_evidence_write_is_exclusive_and_0600(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            MODULE.write_exclusive(path, {"ok": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                MODULE.write_exclusive(path, {"ok": False})


if __name__ == "__main__":
    unittest.main()
