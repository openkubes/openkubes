import copy
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evidence_observer_protocol_test", HERE / "verify_evidence_observer_protocol.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
BUNDLE = MODULE.BUNDLE


class EvidenceObserverProtocolTests(unittest.TestCase):
    def setUp(self):
        self.path = HERE / "evidence-observer-protocol-v1.yaml"
        self.protocol = MODULE.V1.read_yaml_or_json(self.path)
        self.context = {
            "runId": "ok141-offline-test",
            "createdAt": "2026-08-10T17:02:00Z",
            "protocolDigest": "sha256:" + "1" * 64,
            "fixtureDigest": "sha256:" + "2" * 64,
            "decisionInputDigest": BUNDLE.DECISION_INPUT_DIGEST,
            "targetIdentities": {"ok-mgmt": {"uid": "test-uid"}},
            "observedFrom": "2026-08-10T17:00:00Z",
            "observedUntil": "2026-08-10T17:01:00Z",
            "clockSource": "offline-test-clock",
            "maximumClockSkewSeconds": 5,
        }

    def assert_protocol_rejected(self, changed):
        with self.assertRaises(MODULE.V1.HarnessError):
            MODULE.validate(changed, self.path)

    def test_protocol_and_source_verify(self):
        self.assertTrue(MODULE.validate(self.protocol, self.path).startswith("sha256:"))

    def test_external_write_or_gate_fails_closed(self):
        for field in ("externalWriteAuthorized", "credentialMutationAuthorized", "infrastructureMutationAuthorized", "m0aInstallationGranted", "m0bInstallationGranted", "go1Granted"):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["authorization"][field] = True
            with self.subTest(field=field):
                self.assert_protocol_rejected(changed)

    def test_publication_cannot_be_enabled(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["bundleContract"]["publication"]["authorized"] = True
        self.assert_protocol_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["bundleContract"]["publication"]["credentialStatus"] = "ISSUED"
        self.assert_protocol_rejected(changed)

    def test_tag_cannot_become_authoritative(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["destination"]["tagAuthority"] = "AUTHORITATIVE"
        self.assert_protocol_rejected(changed)

    def test_destination_cannot_overclaim_retention_or_availability(self):
        for field, value in (("retentionPolicy", "PROVEN"), ("accessProof", "PROVEN"), ("availabilityClaim", "PROVEN"), ("adminDeletionPossible", False)):
            changed = copy.deepcopy(self.protocol)
            changed["spec"]["destination"][field] = value
            with self.subTest(field=field):
                self.assert_protocol_rejected(changed)

    def test_observer_cannot_be_predeployed_or_human_independent(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["observers"]["security"]["status"] = "DEPLOYED"
        self.assert_protocol_rejected(changed)
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["observers"]["security"]["claimBoundary"] = "Independent human review is proven."
        self.assert_protocol_rejected(changed)

    def test_clock_cannot_be_preproven(self):
        changed = copy.deepcopy(self.protocol)
        changed["spec"]["timePolicy"]["currentSkewEvidence"] = "PROVEN"
        self.assert_protocol_rejected(changed)

    def test_clean_bundle_builds_and_verifies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "status.json").write_text('{"ready":true,"reason":"current"}\n')
            (root / "events.log").write_text("observer started\nobserver complete\n")
            manifest = BUNDLE.build(root, self.context)
            self.assertEqual(BUNDLE.verify(root, manifest), manifest["spec"]["bundleDigest"])
            self.assertEqual([item["path"] for item in manifest["spec"]["artifacts"]], ["events.log", "status.json"])

    def test_artifact_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "status.json"
            artifact.write_text('{"ready":true}\n')
            manifest = BUNDLE.build(root, self.context)
            artifact.write_text('{"ready":false}\n')
            with self.assertRaises(BUNDLE.EvidenceError):
                BUNDLE.verify(root, manifest)

    def test_secret_kubeconfig_and_key_material_fail_closed(self):
        cases = {
            "secret.yaml": "apiVersion: v1\nkind: Secret\nmetadata:\n  name: forbidden\n",
            "cluster-kubeconfig.yaml": "apiVersion: v1\nkind: Config\n",
            "evidence.json": '{"client-key-data":"forbidden"}\n',
            "events.log": "Authorization: Bearer forbidden-token\n",
            "identity.pem": "-----BEGIN PRIVATE KEY-----\nforbidden\n",
        }
        for name, content in cases.items():
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / name).write_text(content)
                with self.subTest(name=name), self.assertRaises(BUNDLE.EvidenceError):
                    BUNDLE.build(root, self.context)

    def test_wrong_decision_binding_or_clock_fails_closed(self):
        changed = dict(self.context)
        changed["decisionInputDigest"] = "sha256:" + "3" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "status.json").write_text('{"ready":true}\n')
            with self.assertRaises(BUNDLE.EvidenceError):
                BUNDLE.build(root, changed)
            changed = dict(self.context)
            changed["observedUntil"] = "2026-08-10T17:03:00Z"
            with self.assertRaises(BUNDLE.EvidenceError):
                BUNDLE.build(root, changed)

    def test_manifest_authorization_or_digest_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "status.json").write_text('{"ready":true}\n')
            manifest = BUNDLE.build(root, self.context)
            changed = copy.deepcopy(manifest)
            changed["spec"]["authorization"]["publicationAuthorized"] = True
            with self.assertRaises((BUNDLE.EvidenceError, MODULE.V1.HarnessError)):
                BUNDLE.verify(root, changed)
            changed = copy.deepcopy(manifest)
            changed["spec"]["bundleDigest"] = "sha256:" + "0" * 64
            with self.assertRaises(BUNDLE.EvidenceError):
                BUNDLE.verify(root, changed)


if __name__ == "__main__":
    unittest.main()
