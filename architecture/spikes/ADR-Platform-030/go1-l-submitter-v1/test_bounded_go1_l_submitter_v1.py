import copy
import datetime as dt
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "go1_l_submitter_test", HERE / "bounded_go1_l_submitter_v1.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Completed:
    returncode = 0


class GO1LSubmitterTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-l-submitter-candidate-v1.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 13, 14, 0, tzinfo=dt.timezone.utc)

    def assert_rejected(self, candidate):
        with self.assertRaises((MODULE.SubmitterError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(candidate, self.path)

    def authority_fixture(self, directory: Path, operation: str, predecessor=None):
        credential = directory / "credential.kubeconfig"
        credential.write_text("apiVersion: v1\nkind: Config\n")
        os.chmod(credential, 0o600)
        receipt = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "CredentialReceipt",
            "spec": {
                "operation": operation,
                "targetPlane": next(item["targetPlane"] for item in self.candidate["spec"]["operations"] if item["id"] == operation),
                "issuedAt": "2026-08-13T13:59:00Z",
                "expiresAt": "2026-08-13T14:10:00Z",
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
                "operationGranted": operation,
                "candidateDigest": MODULE.sha(self.path),
                "protocolDigest": self.candidate["spec"]["sourceProtocol"]["digest"],
                "grantID": "ok141-go1-l-test-only",
                "singleRun": True,
                "issuedAt": "2026-08-13T13:58:00Z",
                "expiresAt": "2026-08-13T14:12:00Z",
                "credentialReceiptDigest": MODULE.sha(receipt_path),
                "predecessorEvidenceDigests": predecessor or [],
            },
        }
        return grant, receipt, receipt_path, credential

    def test_candidate_and_three_plans_reproduce(self):
        reviewed = MODULE.validate_candidate(self.candidate, self.path)
        self.assertEqual(set(reviewed), {"provider-prerequisites", "capi-lifecycle", "helmchartproxy"})
        self.assertEqual(sum(len(item.documents) for item in reviewed.values()), 12)
        for operation in reviewed:
            plan = MODULE.build_plan(self.candidate, self.path, operation)
            self.assertFalse(plan["mutationAuthorized"])
            self.assertFalse(plan["clusterContacted"])

    def test_candidate_authority_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["mutationAuthorized"] = True
        self.assert_rejected(changed)

    def test_protocol_binding_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["sourceProtocol"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_manifest_binding_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0]["semanticDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_operation_order_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0], changed["spec"]["operations"][1] = changed["spec"]["operations"][1], changed["spec"]["operations"][0]
        self.assert_rejected(changed)

    def test_authority_plane_swap_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)

    def test_non_create_transport_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["transport"]["serverSideApply"] = True
        self.assert_rejected(changed)

    def test_expired_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            grant["spec"]["expiresAt"] = "2026-08-13T13:59:30Z"
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_wrong_candidate_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            grant["spec"]["candidateDigest"] = "sha256:" + "0" * 64
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_missing_predecessor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "capi-lifecycle")
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "capi-lifecycle", grant, receipt, receipt_path, credential, self.now)

    def test_secret_bearing_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            receipt["spec"]["token"] = "forbidden"
            receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=True))
            grant["spec"]["credentialReceiptDigest"] = MODULE.sha(receipt_path)
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_credential_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            os.chmod(credential, 0o644)
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_fixed_create_transport_with_fake_runner(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            result = MODULE.execute_once(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now, runner=runner)
        self.assertEqual(result["objectCount"], 3)
        self.assertEqual(calls[0][0][0], "kubectl")
        self.assertEqual(calls[0][0][-3:], ["create", "--filename", "-"])
        self.assertEqual(calls[0][1]["input"], (HERE.parent / "harness/projections/phase-r-v4/ok-infra-prerequisites.yaml").read_bytes())


if __name__ == "__main__":
    unittest.main()
