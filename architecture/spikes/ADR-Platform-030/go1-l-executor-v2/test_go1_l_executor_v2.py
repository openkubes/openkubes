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
SPEC = importlib.util.spec_from_file_location("ok141_go1_l_executor_v2_test", HERE / "bounded_go1_l_executor_v2.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Completed:
    def __init__(self, stdout=b"", returncode=0):
        self.stdout = stdout
        self.stderr = b""
        self.returncode = returncode


class GO1LExecutorV2Tests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)
        self.identities = {
            "ok-infra": "sha256:0cab42fab537845afb82ef510169bf9402e314e0fcb3ebce972499e0a1cd8f13",
            "ok-mgmt": "sha256:32a164332776f37129e46415af79945745134fefe80c5237d43fe13fa0511ffe",
        }

    def write_preflight(self, directory: Path, identities=None):
        value = {
            "spec": {
                "candidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
                "result": "PASS-FRESH-BASELINE-AND-PREREQUISITES",
                "mutationPerformed": False,
                "secretBodiesRetained": False,
                "freshUntil": "2026-08-14T12:05:00Z",
                "credentialIdentityDigests": identities or self.identities,
            }
        }
        path = directory / "preflight.json"
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def write_receipt(self, directory: Path, filename: str, operation: str, plane: str, credential: str, identity: str):
        value = {
            "apiVersion": "evidence.openkubes.io/v1alpha1",
            "kind": "CredentialReceipt",
            "spec": {
                "operation": operation,
                "targetPlane": plane,
                "credentialPath": credential,
                "credentialIdentityDigest": identity,
                "issuedAt": "2026-08-14T11:59:00Z",
                "expiresAt": "2026-08-14T12:10:00Z",
                "tokenBytesPersisted": False,
                "tokenBytesEmitted": False,
            },
        }
        path = directory / filename
        path.write_text(yaml.safe_dump(value, sort_keys=True))
        return path

    def write_grant(self, directory: Path, operation: str, preflight: Path, receipts: dict[str, Path], predecessors=None, provider=False):
        value = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "SingleOperationGrantV2",
            "spec": {
                "decision": "GO",
                "authority": "github:arashkaffamanesh",
                "mutationAuthorized": True,
                "credentialUseGranted": True,
                "go1LGranted": True,
                "go1Granted": False,
                "retryGranted": False,
                "rollbackOrCleanupGranted": False,
                "evidencePublicationGranted": False,
                "failureInjectionGranted": False,
                "operationGranted": operation,
                "candidateDigest": MODULE.V1.sha(MODULE.CANDIDATE),
                "executorV1Digest": "sha256:206b62b955d7709f69601989d91b7b5938afba03b2235a4909c64fcecd4fac70",
                "protocolDigest": "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885",
                "fixtureDigest": MODULE.V1.FIXTURE_DIGEST,
                "preflightCandidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2",
                "preflightEvidenceDigest": MODULE.V1.sha(preflight),
                "clientDigest": MODULE.V1.CLIENT_DIGEST,
                "credentialIdentityClosureDigest": "sha256:26c840ac3e1c5eb879f107801740edb0db73a717fea9c00123ad1e36b3fdc008",
                "grantID": "ok141-go1-l-executor-v2-test-only",
                "singleRun": True,
                "issuedAt": "2026-08-14T11:58:00Z",
                "expiresAt": "2026-08-14T12:12:00Z",
                "credentialReceiptDigests": {name: MODULE.V1.sha(path) for name, path in receipts.items()},
                "predecessorEvidenceDigests": [MODULE.V1.sha(path) for path in (predecessors or [])],
                "sourceCredentialReadGranted": provider,
                "destinationCredentialUseGranted": provider,
                "secretMaterializationGranted": provider,
            },
        }
        path = directory / "grant.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=True))
        return path

    def runner(self, calls):
        def run(command, **kwargs):
            calls.append((command, kwargs))
            if command[-3:] == ["version", "--client", "--output=json"]:
                return Completed(json.dumps({"clientVersion": {"gitVersion": "v1.34.1", "platform": "darwin/amd64"}}).encode())
            return Completed()
        return run

    def test_candidate_is_inert_and_supersedes_v1(self):
        candidate, _, _ = MODULE.validate_candidate()
        plan = MODULE.plan()
        self.assertEqual((HERE / "go1-l-executor-candidate-v2.sha256").read_text().strip(), MODULE.V1.sha(MODULE.CANDIDATE))
        self.assertEqual(candidate["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO")
        self.assertTrue(plan["pointOfUseCredentialIdentityRequired"])
        self.assertFalse(plan["mutationAuthorized"])
        self.assertFalse(plan["clusterContacted"])

    def test_static_transport_checks_point_of_use_identity(self):
        calls = []
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.write_preflight(directory)
            receipt = self.write_receipt(directory, "receipt.yaml", "provider-prerequisites", "ok-infra", "/Users/arash/.kube/ok-infra.yaml", self.identities["ok-infra"])
            grant = self.write_grant(directory, "provider-prerequisites", preflight, {"provider-prerequisites": receipt})
            with mock.patch.object(MODULE, "inspect_identity", return_value={"identityDigest": self.identities["ok-infra"]}):
                result = MODULE.execute_static(MODULE.CANDIDATE, "provider-prerequisites", grant, receipt, preflight, [], self.now, runner=self.runner(calls))
        self.assertTrue(result["credentialIdentityVerifiedAtPointOfUse"])
        self.assertEqual(calls[1][0], [str(MODULE.V1.CLIENT), "--kubeconfig", "/Users/arash/.kube/ok-infra.yaml", "create", "--filename", "-"])

    def test_changed_current_identity_fails_before_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.write_preflight(directory)
            receipt = self.write_receipt(directory, "receipt.yaml", "provider-prerequisites", "ok-infra", "/Users/arash/.kube/ok-infra.yaml", self.identities["ok-infra"])
            grant = self.write_grant(directory, "provider-prerequisites", preflight, {"provider-prerequisites": receipt})
            with mock.patch.object(MODULE, "inspect_identity", return_value={"identityDigest": "sha256:" + "0" * 64}):
                with self.assertRaises(MODULE.ExecutorV2Error):
                    MODULE.validate_runtime(MODULE.CANDIDATE, "provider-prerequisites", grant, preflight, [], [(receipt, "provider-prerequisites", "ok-infra", Path("/Users/arash/.kube/ok-infra.yaml"))], self.now)

    def test_stale_preflight_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            changed = {**self.identities, "ok-mgmt": "sha256:" + "0" * 64}
            preflight = self.write_preflight(directory, changed)
            receipt = self.write_receipt(directory, "receipt.yaml", "provider-prerequisites", "ok-infra", "/Users/arash/.kube/ok-infra.yaml", self.identities["ok-infra"])
            grant = self.write_grant(directory, "provider-prerequisites", preflight, {"provider-prerequisites": receipt})
            with self.assertRaises(MODULE.ExecutorV2Error):
                MODULE.validate_runtime(MODULE.CANDIDATE, "provider-prerequisites", grant, preflight, [], [(receipt, "provider-prerequisites", "ok-infra", Path("/Users/arash/.kube/ok-infra.yaml"))], self.now)

    def test_provider_transport_checks_both_identities(self):
        calls = []
        valid_source = b"""apiVersion: v1
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
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.write_preflight(directory)
            source_receipt = self.write_receipt(directory, "source.yaml", "provider-access-source", "ok-infra", "/Users/arash/.kube/ok-infra.yaml", self.identities["ok-infra"])
            destination_receipt = self.write_receipt(directory, "destination.yaml", "provider-access-secret", "ok-mgmt", "/Users/arash/.kube/ok-mgmt.yaml", self.identities["ok-mgmt"])
            predecessors = [directory / "p1.json", directory / "p2.json"]
            for index, path in enumerate(predecessors):
                path.write_text(json.dumps({"operation": index + 1}))
            grant = self.write_grant(directory, "provider-access-secret", preflight, {"provider-access-source": source_receipt, "provider-access-secret": destination_receipt}, predecessors, provider=True)

            def identity(path):
                plane = "ok-infra" if path.name == "ok-infra.yaml" else "ok-mgmt"
                return {"identityDigest": self.identities[plane]}

            with mock.patch.object(MODULE, "inspect_identity", side_effect=identity):
                result = MODULE.execute_provider(MODULE.CANDIDATE, grant, source_receipt, destination_receipt, preflight, predecessors, self.now, runner=self.runner(calls), source_reader=lambda _: valid_source)
        self.assertTrue(result["credentialIdentitiesVerifiedAtPointOfUse"])
        self.assertEqual(calls[1][0], [str(MODULE.V1.CLIENT), "--kubeconfig", "/Users/arash/.kube/ok-mgmt.yaml", "create", "--filename", "-"])
        self.assertNotIn("provider.invalid", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
