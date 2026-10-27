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
SPEC = importlib.util.spec_from_file_location("ok141_go1_l_executor_v1", HERE / "bounded_go1_l_executor_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Completed:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class GO1LExecutorTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)

    def authority_fixture(self, directory: Path):
        preflight = {
            "spec": {
                "candidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
                "result": "PASS-FRESH-BASELINE-AND-PREREQUISITES",
                "mutationPerformed": False,
                "secretBodiesRetained": False,
                "freshUntil": "2026-08-14T12:05:00Z",
            }
        }
        preflight_path = directory / "preflight.json"
        preflight_path.write_text(json.dumps(preflight, sort_keys=True))
        receipt = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "CredentialReceipt",
            "spec": {
                "operation": "provider-prerequisites",
                "targetPlane": "ok-infra",
                "issuedAt": "2026-08-14T11:59:00Z",
                "expiresAt": "2026-08-14T12:10:00Z",
                "tokenBytesPersisted": False,
                "tokenBytesEmitted": False,
            },
        }
        receipt_path = directory / "receipt.yaml"
        receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=True))
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "SingleOperationGrant",
            "spec": {
                "decision": "GO",
                "mutationAuthorized": True,
                "go1LGranted": True,
                "operationGranted": "provider-prerequisites",
                "candidateDigest": MODULE.sha(MODULE.CANDIDATE),
                "protocolDigest": "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885",
                "fixtureDigest": MODULE.FIXTURE_DIGEST,
                "preflightCandidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
                "preflightEvidenceDigest": MODULE.sha(preflight_path),
                "clientDigest": MODULE.CLIENT_DIGEST,
                "grantID": "ok141-go1-l-executor-v1-test-only",
                "singleRun": True,
                "issuedAt": "2026-08-14T11:58:00Z",
                "expiresAt": "2026-08-14T12:12:00Z",
                "credentialReceiptDigest": MODULE.sha(receipt_path),
                "predecessorEvidenceDigests": [],
            },
        }
        grant_path = directory / "grant.yaml"
        grant_path.write_text(yaml.safe_dump(grant, sort_keys=True))
        return preflight_path, receipt_path, grant_path

    def test_candidate_and_plan_are_inert_and_exact(self):
        candidate, _, _ = MODULE.validate_candidate()
        plan = MODULE.plan()
        self.assertEqual((HERE / "go1-l-executor-candidate-v1.sha256").read_text().strip(), MODULE.sha(MODULE.CANDIDATE))
        self.assertEqual(candidate["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO")
        self.assertEqual([item["id"] for item in plan["operations"]], ["provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle", "helmchartproxy"])
        self.assertTrue(all(item["client"] == str(MODULE.CLIENT) for item in plan["operations"]))
        self.assertEqual(sum(item["objectCount"] for item in plan["operations"]), 13)
        self.assertFalse(plan["credentialUseGranted"])
        self.assertFalse(plan["mutationAuthorized"])
        self.assertFalse(plan["clusterContacted"])

    def test_exact_client_is_valid(self):
        MODULE.verify_client()

    def test_stale_first_operation_preflight_fails(self):
        historical = HERE.parent / "go1-v6-preflight-v2" / "preflight-v2-redacted-closure-candidate.yaml"
        with self.assertRaises((MODULE.ExecutorError, ValueError, KeyError)):
            MODULE.validate_preflight(historical, MODULE.sha(historical), MODULE.V3.V2.parse_time("2026-08-14T12:00:00Z"), True)

    def test_exact_client_create_transport_is_fixed(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            if command[-3:] == ["version", "--client", "--output=json"]:
                return Completed(json.dumps({"clientVersion": {"gitVersion": "v1.34.1", "platform": "darwin/amd64"}}).encode())
            return Completed()

        with tempfile.TemporaryDirectory() as temp:
            preflight, receipt, grant = self.authority_fixture(Path(temp))
            with mock.patch.object(MODULE, "validate_file"):
                result = MODULE.execute_static(
                    MODULE.CANDIDATE,
                    "provider-prerequisites",
                    grant,
                    receipt,
                    Path("/Users/arash/.kube/ok-infra.yaml"),
                    preflight,
                    [],
                    self.now,
                    runner=runner,
                )
        self.assertEqual(result["objectCount"], 3)
        self.assertEqual(calls[1][0], [str(MODULE.CLIENT), "--kubeconfig", "/Users/arash/.kube/ok-infra.yaml", "create", "--filename", "-"])
        reviewed = MODULE.V3.validate_candidate(MODULE.V3.load_candidate(), MODULE.V3.CANDIDATE)["provider-prerequisites"]
        self.assertEqual(MODULE.V3.V1.sha256_bytes(calls[1][1]["input"]), reviewed.raw_digest)

    def test_secret_bearing_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            preflight, _, grant_path = self.authority_fixture(Path(temp))
            grant = yaml.safe_load(grant_path.read_text())
            grant["spec"]["token"] = "forbidden"
            with self.assertRaises(MODULE.ExecutorError):
                MODULE.validate_common(MODULE.CANDIDATE, "provider-prerequisites", grant, preflight, [], self.now)


if __name__ == "__main__":
    unittest.main()
