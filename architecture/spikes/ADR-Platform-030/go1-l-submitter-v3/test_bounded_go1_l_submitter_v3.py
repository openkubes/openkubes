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
SPEC = importlib.util.spec_from_file_location("go1_l_submitter_v3_test", HERE / "bounded_go1_l_submitter_v3.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class Completed:
    returncode = 0


class GO1LSubmitterV3Tests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "go1-l-submitter-candidate-v3.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)

    def assert_rejected(self, candidate):
        with self.assertRaises((MODULE.SubmitterError, MODULE.V2.SubmitterError, MODULE.HCPA.AmendmentError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(candidate, self.path)

    def authority_fixture(self, directory: Path, operation: str, predecessors=None):
        credential = directory / "credential.kubeconfig"
        credential.write_text("apiVersion: v1\nkind: Config\n")
        os.chmod(credential, 0o600)
        item = next(value for value in self.candidate["spec"]["operations"] if value["id"] == operation)
        receipt = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "CredentialReceipt", "spec": {"operation": operation, "targetPlane": item["targetPlane"], "issuedAt": "2026-08-14T11:59:00Z", "expiresAt": "2026-08-14T12:10:00Z", "tokenBytesPersisted": False, "tokenBytesEmitted": False}}
        receipt_path = directory / "receipt.yaml"
        receipt_path.write_text(yaml.safe_dump(receipt, sort_keys=True))
        grant = {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "SingleOperationGrant", "spec": {"decision": "GO", "mutationAuthorized": True, "go1LGranted": True, "operationGranted": operation, "candidateDigest": MODULE.V2.sha(self.path), "fixtureDigest": self.candidate["spec"]["fixture"]["fixtureDigest"], "preflightDigest": self.candidate["spec"]["sourcePreflight"]["digest"], "grantID": "ok141-go1-l-v3-test-only", "singleRun": True, "issuedAt": "2026-08-14T11:58:00Z", "expiresAt": "2026-08-14T12:12:00Z", "credentialReceiptDigest": MODULE.V2.sha(receipt_path), "predecessorEvidenceDigests": predecessors or []}}
        return grant, receipt, receipt_path, credential

    def test_candidate_binds_four_runtime_eligible_operations(self):
        reviewed = MODULE.validate_candidate(self.candidate, self.path)
        self.assertEqual(list(reviewed), ["provider-prerequisites", "management-namespace", "capi-lifecycle", "helmchartproxy"])
        self.assertEqual(sum(len(item.documents) for item in reviewed.values()), 12)
        self.assertTrue(all(item.runtime_eligible for item in reviewed.values()))

    def test_inherited_operation_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][0]["targetPlane"] = "ok-mgmt"
        self.assert_rejected(changed)

    def test_hcp_digest_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][3]["semanticDigest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_hcp_cannot_be_disabled_in_v3_binding(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["operations"][3]["runtimeEligible"] = False
        self.assert_rejected(changed)

    def test_any_merged_authority_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["go1LGranted"] = True
        self.assert_rejected(changed)

    def test_external_materializer_cannot_move_into_submitter(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["externalPrerequisite"]["executedByThisTool"] = True
        self.assert_rejected(changed)

    def test_missing_hcp_predecessor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "helmchartproxy")
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "helmchartproxy", grant, receipt, receipt_path, credential, self.now)

    def test_wrong_candidate_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            grant["spec"]["candidateDigest"] = "sha256:" + "0" * 64
            with self.assertRaises(MODULE.V2.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_credential_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "provider-prerequisites")
            os.chmod(credential, 0o644)
            with self.assertRaises(MODULE.SubmitterError):
                MODULE.validate_runtime_authority(self.candidate, self.path, "provider-prerequisites", grant, receipt, receipt_path, credential, self.now)

    def test_fixed_create_transport_with_current_hcp(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        with tempfile.TemporaryDirectory() as temp:
            grant, receipt, receipt_path, credential = self.authority_fixture(Path(temp), "helmchartproxy", ["sha256:" + "1" * 64])
            result = MODULE.execute_once(self.candidate, self.path, "helmchartproxy", grant, receipt, receipt_path, credential, self.now, runner=runner)
        self.assertEqual(result["objectCount"], 1)
        self.assertEqual(calls[0][0][-3:], ["create", "--filename", "-"])
        self.assertEqual(MODULE.V1.sha256_bytes(calls[0][1]["input"]), "sha256:d2d93b5868bd9cba7b288ac117c5ceb08605b729c1e2eeae86ee001ed52887f0")


if __name__ == "__main__":
    unittest.main()
