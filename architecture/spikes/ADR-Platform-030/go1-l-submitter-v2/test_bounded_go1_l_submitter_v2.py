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
SPEC = importlib.util.spec_from_file_location("go1_l_submitter_v2_test", HERE / "bounded_go1_l_submitter_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Completed:
    returncode = 0


class GO1LSubmitterV2Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-l-submitter-candidate-v2.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 14, 10, 0, tzinfo=dt.timezone.utc)

    def assert_rejected(self, candidate):
        with self.assertRaises((MODULE.SubmitterError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(candidate, self.path)

    def authority_fixture(self, directory: Path, operation: str, predecessors=None):
        credential = directory / "credential.kubeconfig"
        credential.write_text("apiVersion: v1\nkind: Config\n")
        os.chmod(credential, 0o600)
        item = next(value for value in self.candidate["spec"]["operations"] if value["id"] == operation)
        receipt = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "CredentialReceipt", "spec": {"operation": operation, "targetPlane": item["targetPlane"], "issuedAt": "2026-08-14T09:59:00Z", "expiresAt": "2026-08-14T10:10:00Z", "tokenBytesPersisted": False, "tokenBytesEmitted": False}}
        receipt_path = directory / "receipt.yaml"
        receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=True))
        grant = {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "SingleOperationGrant", "spec": {"decision": "GO", "mutationAuthorized": True, "go1LGranted": True, "operationGranted": operation, "candidateDigest": MODULE.sha(self.path), "fixtureDigest": self.candidate["spec"]["fixture"]["fixtureDigest"], "preflightDigest": self.candidate["spec"]["sourcePreflight"]["digest"], "grantID": "ok141-go1-l-v2-test-only", "singleRun": True, "issuedAt": "2026-08-14T09:58:00Z", "expiresAt": "2026-08-14T10:12:00Z", "credentialReceiptDigest": MODULE.sha(receipt_path), "predecessorEvidenceDigests": predecessors or []}}
        return grant, receipt, receipt_path, credential

    def test_candidate_and_four_plans_reproduce(self):
        reviewed = MODULE.validate_candidate(self.candidate, self.path)
        self.assertEqual(list(reviewed), ["provider-prerequisites", "management-namespace", "capi-lifecycle", "helmchartproxy"])
        self.assertEqual(sum(len(item.documents) for item in reviewed.values()), 12)
        self.assertEqual(sum(item.runtime_eligible for item in reviewed.values()), 3)
        for operation in reviewed:
            plan = MODULE.build_plan(self.candidate, self.path, operation)
            self.assertFalse(plan["mutationAuthorized"])
            self.assertFalse(plan["clusterContacted"])

    def test_authority_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["mutationAuthorized"] = True
        self.assert_rejected(changed)

    def test_fixture_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["fixture"]["fixtureDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_slice_overlap_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][2]["documentIndices"][0] = 0
        self.assert_rejected(changed)

    def test_slice_payload_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][1]["payloadRawDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_secret_cannot_enter_static_projection(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][1]["documentIndices"] = [2]
        self.assert_rejected(changed)

    def test_external_materializer_cannot_be_claimed_by_tool(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["externalPrerequisite"]["executedByThisTool"] = True
        self.assert_rejected(changed)

    def test_hcp_is_fail_closed_for_historical_r(self):
        reviewed = MODULE.validate_candidate(self.candidate, self.path)
        self.assertFalse(reviewed["helmchartproxy"].runtime_eligible)
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "helmchartproxy", ["sha256:" + "1" * 64])
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "helmchartproxy", grant, receipt, receipt_path, credential, self.now)

    def test_missing_two_lifecycle_predecessors_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "capi-lifecycle", ["sha256:" + "1" * 64])
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "capi-lifecycle", grant, receipt, receipt_path, credential, self.now)

    def test_expired_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            grant["spec"]["expiresAt"] = "2026-08-14T09:59:30Z"
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

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

    def test_fixed_create_transport_with_sliced_payload(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as temp:
            predecessors = ["sha256:" + "1" * 64]
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "management-namespace", predecessors)
            result = MODULE.execute_once(self.candidate, self.path, "management-namespace", grant, receipt, receipt_path, credential, self.now, runner=runner)
        self.assertEqual(result["objectCount"], 1)
        self.assertEqual(calls[0][0][-3:], ["create", "--filename", "-"])
        self.assertEqual(MODULE.V1.sha256_bytes(calls[0][1]["input"]), "sha256:fbee2a6568c3f1d8ba626724ee36c7cfd38145e37b68f8319a5de87a7c4b3b11")


if __name__ == "__main__":
    unittest.main()
