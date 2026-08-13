from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import verify_m0a_v7_boundary as module  # noqa: E402


def write_partition(tmp_path: Path, mutate) -> Path:
    value = yaml.safe_load(module.PARTITION.read_text())
    source = value["spec"]["source"]
    admission = value["spec"]["admission"]
    source["path"] = str((module.PARTITION.parent / source["path"]).resolve())
    admission["path"] = str((module.PARTITION.parent / admission["path"]).resolve())
    mutate(value)
    path = tmp_path / "partition.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    return path


class BoundaryTests(unittest.TestCase):
    def mutate_and_verify(self, mutate):
        with tempfile.TemporaryDirectory() as directory:
            return module.verify(write_partition(Path(directory), mutate))

    def test_partition_and_admission_verify_offline(self) -> None:
        self.assertEqual(module.verify(), {
            "state": "OFFLINE-ONLY-NO-GO",
            "sourceObjects": 19,
            "administratorObjects": 8,
            "temporaryInstallerObjects": 11,
            "clusterScopedAdmissionIdentities": 4,
            "namespacedAdmissionIdentities": 7,
            "mutationAuthorized": False,
            "clusterContacted": False,
        })

    def test_partition_checkpoint_digest_is_bound(self) -> None:
        actual = "sha256:" + hashlib.sha256(module.PARTITION.read_bytes()).hexdigest()
        expected = (module.HERE / "m0a-v7-authority-partition-v1.sha256").read_text().strip()
        self.assertEqual(actual, expected)

    def test_duplicate_identity_fails_closed(self) -> None:
        def mutate(value):
            identities = value["spec"]["authorityDomains"]["temporaryInstaller"]["identities"]
            identities[-1] = copy.deepcopy(identities[0])

        with self.assertRaisesRegex(module.BoundaryError, "unique temporaryInstaller identities"):
            self.mutate_and_verify(mutate)

    def test_missing_identity_fails_closed(self) -> None:
        def mutate(value):
            value["spec"]["authorityDomains"]["temporaryInstaller"]["identities"][-1]["name"] = "wrong"

        with self.assertRaisesRegex(module.BoundaryError, "identities in reviewed source"):
            self.mutate_and_verify(mutate)

    def test_cross_domain_overlap_fails_closed(self) -> None:
        def mutate(value):
            installer = value["spec"]["authorityDomains"]["temporaryInstaller"]["identities"]
            value["spec"]["authorityDomains"]["administrator"]["identities"][-1] = copy.deepcopy(installer[0])

        with self.assertRaises(module.BoundaryError):
            self.mutate_and_verify(mutate)

    def test_mutation_authorization_fails_closed(self) -> None:
        def mutate(value):
            value["spec"]["authorization"]["mutationAuthorized"] = True

        with self.assertRaisesRegex(module.BoundaryError, "mutation authorization"):
            self.mutate_and_verify(mutate)

    def test_expected_expression_never_reads_namespace_for_cluster_scope(self) -> None:
        spec = yaml.safe_load(module.PARTITION.read_text())["spec"]
        identities = spec["authorityDomains"]["temporaryInstaller"]["identities"]
        cluster = [item for item in identities if not item["namespace"]]
        namespaced = [item for item in identities if item["namespace"]]
        self.assertNotIn("request.namespace", module.expected_expression(cluster, False))
        self.assertIn("request.namespace == x.namespace", module.expected_expression(namespaced, True))


if __name__ == "__main__":
    unittest.main()
