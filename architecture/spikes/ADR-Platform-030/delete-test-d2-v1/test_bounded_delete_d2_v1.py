#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import yaml

import bounded_delete_d2_v1 as runner


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d2-candidate-v1.yaml"


class DeleteD2V1Test(unittest.TestCase):
    def changed(self, mutate) -> Path:
        value = yaml.safe_load(CANDIDATE.read_text())
        mutate(value)
        temp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False)
        yaml.safe_dump(value, temp, sort_keys=False)
        temp.close()
        self.addCleanup(Path(temp.name).unlink)
        return Path(temp.name)

    @staticmethod
    def hcp(uid="hcp-uid"):
        return {"metadata": {"name": "disposable-ok141-cilium", "namespace": "disposable-ok141", "uid": uid, "resourceVersion": "10"}}

    @staticmethod
    def hrp(uid="hcp-uid", name="generated"):
        return {"metadata": {"name": name, "namespace": "disposable-ok141", "uid": "hrp-uid", "resourceVersion": "20", "ownerReferences": [{"apiVersion": "addons.cluster.x-k8s.io/v1alpha1", "kind": "HelmChartProxy", "name": "disposable-ok141-cilium", "uid": uid, "controller": True}]}}

    def test_candidate_passes(self):
        self.assertEqual("OFFLINE-PREPARED-BLOCKED-NO-GO", runner.verify_candidate(CANDIDATE)["spec"]["state"])

    def test_candidate_cannot_grant_delete(self):
        with self.assertRaisesRegex(runner.D2Error, "grants authority"):
            runner.verify_candidate(self.changed(lambda v: v["spec"]["authorization"].update(deleteGranted=True)))

    def test_target_change_fails(self):
        with self.assertRaisesRegex(runner.D2Error, "target mismatch"):
            runner.verify_candidate(self.changed(lambda v: v["spec"]["target"].update(name="wrong")))

    def test_derive_exact_owner(self):
        self.assertEqual("generated", runner.derive_hrp(self.hcp(), {"items": [self.hrp()]})["metadata"]["name"])

    def test_derive_zero_fails(self):
        with self.assertRaisesRegex(runner.D2Error, "exactly one"):
            runner.derive_hrp(self.hcp(), {"items": []})

    def test_derive_two_fails(self):
        with self.assertRaisesRegex(runner.D2Error, "exactly one"):
            runner.derive_hrp(self.hcp(), {"items": [self.hrp(name="one"), self.hrp(name="two")]})

    def test_live_resource_version_rebound(self):
        bound = {"name": "x", "namespace": "n", "uid": "u", "resourceVersion": "1"}
        current = {"metadata": {"name": "x", "namespace": "n", "uid": "u", "resourceVersion": "2"}}
        self.assertEqual("2", runner.live_record(current, bound)["resourceVersion"])

    def test_uid_change_fails(self):
        bound = {"name": "x", "namespace": "n", "uid": "u", "resourceVersion": "1"}
        current = {"metadata": {"name": "x", "namespace": "n", "uid": "other", "resourceVersion": "2"}}
        with self.assertRaisesRegex(runner.D2Error, "immutable identity"):
            runner.live_record(current, bound)

    def test_publication_candidate_is_non_authorizing(self):
        publication = yaml.safe_load((HERE / "delete-d2-publication-candidate-v1.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE), publication["bindings"]["candidateDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
