import base64
import copy
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("provider_access_materializer_test", HERE / "bounded_provider_access_materializer_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


VALID_KUBECONFIG = b"""apiVersion: v1
kind: Config
current-context: provider
clusters:
- name: infra
  cluster:
    server: https://provider.invalid:6443
users:
- name: provider-user
  user: {}
contexts:
- name: provider
  context:
    cluster: infra
    user: provider-user
"""


class Completed:
    returncode = 0


class ProviderAccessMaterializerTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "provider-access-materializer-candidate-v1.yaml"
        self.candidate = MODULE.load_candidate(self.path)
        self.now = dt.datetime(2026, 8, 14, 14, 0, tzinfo=dt.timezone.utc)

    def assert_rejected(self, candidate):
        with self.assertRaises((MODULE.MaterializerError, MODULE.SUBMITTER.SubmitterError, MODULE.V2.SubmitterError, MODULE.V1.HarnessError)):
            MODULE.validate_candidate(candidate, self.path)

    def authority_fixture(self, directory: Path):
        destination = directory / "ok-mgmt.kubeconfig"
        destination.write_text("apiVersion: v1\nkind: Config\n")
        os.chmod(destination, 0o600)
        source_receipt = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "CredentialReceipt", "spec": {"operation": "provider-access-source", "targetPlane": "ok-infra", "sourcePath": self.candidate["spec"]["sourceCredential"]["path"], "issuedAt": "2026-08-14T13:59:00Z", "expiresAt": "2026-08-14T14:10:00Z", "tokenBytesPersisted": False, "tokenBytesEmitted": False}}
        destination_receipt = {"apiVersion": "evidence.openkubes.io/v1alpha1", "kind": "CredentialReceipt", "spec": {"operation": "provider-access-secret", "targetPlane": "ok-mgmt", "issuedAt": "2026-08-14T13:59:00Z", "expiresAt": "2026-08-14T14:10:00Z", "tokenBytesPersisted": False, "tokenBytesEmitted": False}}
        source_path, destination_path = directory / "source-receipt.yaml", directory / "destination-receipt.yaml"
        source_path.write_text(yaml.safe_dump(source_receipt, sort_keys=True))
        destination_path.write_text(yaml.safe_dump(destination_receipt, sort_keys=True))
        grant = {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "ProviderAccessMaterializationGrant", "spec": {"decision": "GO", "sourceCredentialReadGranted": True, "destinationCredentialUseGranted": True, "secretMaterializationGranted": True, "go1LGranted": True, "operationGranted": "provider-access-secret", "candidateDigest": MODULE.V2.sha(self.path), "fixtureDigest": self.candidate["spec"]["fixture"]["fixtureDigest"], "submitterDigest": self.candidate["spec"]["submitter"]["digest"], "grantID": "ok141-provider-access-test-only", "singleRun": True, "issuedAt": "2026-08-14T13:58:00Z", "expiresAt": "2026-08-14T14:12:00Z", "predecessorEvidenceDigests": ["sha256:" + "1" * 64, "sha256:" + "2" * 64], "sourceCredentialReceiptDigest": MODULE.V2.sha(source_path), "destinationCredentialReceiptDigest": MODULE.V2.sha(destination_path)}}
        return grant, source_receipt, source_path, destination_receipt, destination_path, destination

    def test_candidate_and_plan_are_inert(self):
        MODULE.validate_candidate(self.candidate, self.path)
        plan = MODULE.build_plan(self.candidate, self.path)
        self.assertFalse(plan["sourceCredentialBytesRead"])
        self.assertFalse(plan["secretPayloadBuilt"])
        self.assertNotIn(self.candidate["spec"]["sourceCredential"]["path"], json.dumps(plan))

    def test_any_authority_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["authorization"]["secretMaterializationGranted"] = True
        self.assert_rejected(changed)

    def test_secret_identity_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["secretTemplate"]["metadata"]["name"] = "other"
        self.assert_rejected(changed)

    def test_source_path_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["sourceCredential"]["path"] = "/tmp/other"
        self.assert_rejected(changed)

    def test_submitter_binding_tampering_fails_closed(self):
        changed = copy.deepcopy(self.candidate)
        changed["spec"]["submitter"]["digest"] = "sha256:" + "0" * 64
        self.assert_rejected(changed)

    def test_malformed_kubeconfig_fails_closed(self):
        with self.assertRaises(MODULE.MaterializerError):
            MODULE.build_secret_payload(self.candidate["spec"], b"apiVersion: v1\nkind: Config\n")

    def test_default_source_reader_requires_mode_0600(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.yaml"
            source.write_bytes(VALID_KUBECONFIG)
            os.chmod(source, 0o644)
            with self.assertRaises(MODULE.MaterializerError):
                MODULE.default_source_reader(source)

    def test_missing_predecessor_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            values = self.authority_fixture(Path(temp))
            grant = values[0]
            grant["spec"]["predecessorEvidenceDigests"] = grant["spec"]["predecessorEvidenceDigests"][:1]
            with self.assertRaises(MODULE.MaterializerError):
                MODULE.validate_runtime_authority(self.candidate, self.path, grant, *values[1:], self.now)

    def test_secret_bearing_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            grant, source_receipt, source_path, destination_receipt, destination_path, destination = self.authority_fixture(Path(temp))
            source_receipt["spec"]["token"] = "forbidden"
            source_path.write_text(yaml.safe_dump(source_receipt, sort_keys=True))
            grant["spec"]["sourceCredentialReceiptDigest"] = MODULE.V2.sha(source_path)
            with self.assertRaises(MODULE.MaterializerError):
                MODULE.validate_runtime_authority(self.candidate, self.path, grant, source_receipt, source_path, destination_receipt, destination_path, destination, self.now)

    def test_fixed_create_transport_does_not_return_secret_material(self):
        calls, read_paths = [], []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()

        def source_reader(path):
            read_paths.append(path)
            return VALID_KUBECONFIG

        with tempfile.TemporaryDirectory() as temp:
            values = self.authority_fixture(Path(temp))
            result = MODULE.execute_once(self.candidate, self.path, *values, self.now, runner=runner, source_reader=source_reader)
        self.assertEqual(read_paths, [Path(self.candidate["spec"]["sourceCredential"]["path"])])
        self.assertEqual(calls[0][0][-3:], ["create", "--filename", "-"])
        submitted = json.loads(calls[0][1]["input"])
        self.assertEqual(base64.b64decode(submitted["data"]["kubeconfig"]), VALID_KUBECONFIG)
        retained = json.dumps(result)
        self.assertNotIn("provider.invalid", retained)
        self.assertNotIn(base64.b64encode(VALID_KUBECONFIG).decode(), retained)
        self.assertFalse(result["sourceCredentialBytesEmitted"])
        self.assertFalse(result["sourceContentDigestEmitted"])
        self.assertFalse(result["secretPayloadPersisted"])


if __name__ == "__main__":
    unittest.main()
