#!/usr/bin/env python3

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from verify_delete_test_v1 import PASS, load_yaml, verify


HERE = Path(__file__).resolve().parent
PROTOCOL = HERE / "delete-test-protocol-v1.yaml"
OBSERVATION = HERE / "delete-test-read-only-observation-v1.yaml"
PUBLICATION = HERE / "delete-test-preparation-publication-candidate-v1.yaml"


class DeletePreparationTest(unittest.TestCase):
    def verify_changed(self, protocol: dict, observation: dict | None = None) -> None:
        with tempfile.TemporaryDirectory() as temp:
            protocol_path = Path(temp) / "protocol.yaml"
            observation_path = Path(temp) / "observation.yaml"
            publication_path = Path(temp) / "publication.yaml"
            protocol_path.write_text(yaml.safe_dump(protocol, sort_keys=False))
            observation_path.write_text(
                yaml.safe_dump(observation or load_yaml(OBSERVATION), sort_keys=False)
            )
            publication_path.write_text(PUBLICATION.read_text())
            verify(protocol_path, observation_path, publication_path)

    def test_valid_checkpoint_passes(self) -> None:
        result = verify(PROTOCOL, OBSERVATION, PUBLICATION)
        self.assertEqual(PASS, result["state"])
        self.assertFalse(result["mutationAuthorized"])

    def test_enabled_stage_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["stages"][1]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.verify_changed(protocol)

    def test_granted_delete_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["authorization"]["capiClusterDeleteGranted"] = True
        with self.assertRaisesRegex(ValueError, "no permission"):
            self.verify_changed(protocol)

    def test_direct_cluster_target_change_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["stages"][3]["target"] = "v1|Namespace|_|disposable-ok141"
        with self.assertRaisesRegex(ValueError, "authoritative CAPI Cluster"):
            self.verify_changed(protocol)

    def test_provider_secret_not_retained_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["stages"][3]["retainedDuringStage"] = []
        with self.assertRaisesRegex(ValueError, "retained"):
            self.verify_changed(protocol)

    def test_retained_storage_omission_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["stages"][5]["order"] = protocol["spec"]["stages"][5]["order"][:-2]
        with self.assertRaisesRegex(ValueError, "Retain-policy"):
            self.verify_changed(protocol)

    def test_application_finalizer_fails(self) -> None:
        observation = load_yaml(OBSERVATION)
        observation["spec"]["gitOpsPlane"]["allDeletionFinalizersAbsent"] = False
        with self.assertRaisesRegex(ValueError, "finalizer-free"):
            self.verify_changed(load_yaml(PROTOCOL), observation)

    def test_shared_app_project_fails(self) -> None:
        observation = load_yaml(OBSERVATION)
        observation["spec"]["gitOpsPlane"]["exclusiveAppProjectMembership"] = False
        with self.assertRaisesRegex(ValueError, "exclusive membership"):
            self.verify_changed(load_yaml(PROTOCOL), observation)

    def test_shared_runner_deletion_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["excludedSharedInfrastructure"]["deletionAllowed"] = True
        with self.assertRaisesRegex(ValueError, "shared ok147"):
            self.verify_changed(protocol)

    def test_force_delete_exclusion_fails(self) -> None:
        protocol = load_yaml(PROTOCOL)
        protocol["spec"]["exclusions"] = [
            value for value in protocol["spec"]["exclusions"] if "force deletion" not in value
        ]
        with self.assertRaisesRegex(ValueError, "force delete"):
            self.verify_changed(protocol)

    def test_publication_authority_fails(self) -> None:
        publication = load_yaml(PUBLICATION)
        publication["spec"]["authorization"]["commitGranted"] = True
        with tempfile.TemporaryDirectory() as temp:
            publication_path = Path(temp) / "publication.yaml"
            publication_path.write_text(yaml.safe_dump(publication, sort_keys=False))
            with self.assertRaisesRegex(ValueError, "grants authority"):
                verify(PROTOCOL, OBSERVATION, publication_path)


if __name__ == "__main__":
    unittest.main()
