#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_delete_d0_binding_v2 import (
    BindingError,
    DERIVED_RULE,
    amended_runtime_candidate,
    apply_post_filter,
    canonical_digest,
    file_digest,
    verify_candidate,
    verify_grant,
    vm_data_volume_names,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d0-binding-candidate-v2.yaml"


class DeleteD0V2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_yaml(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    @staticmethod
    def virtual_machines() -> list[dict]:
        return [
            {"spec": {"dataVolumeTemplates": [{"metadata": {"name": "cp-disk"}}]}},
            {"spec": {"dataVolumeTemplates": [{"metadata": {"name": "worker-disk"}}]}},
        ]

    def test_candidate_passes(self) -> None:
        candidate, runtime = verify_candidate(CANDIDATE)
        self.assertEqual("NO-GO", candidate["spec"]["authorization"]["decision"])
        self.assertEqual("sha256:7f2b5b578b94a3342fbaae38ac4a673baac542382eb3226ff530b1ecba816514", runtime["spec"]["tool"]["queryProfileDigest"])

    def test_candidate_grants_nothing(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["authorization"]["deleteGranted"] = True
        with self.assertRaisesRegex(BindingError, "grants authority"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_only_data_volume_query_changes(self) -> None:
        candidate, runtime = verify_candidate(CANDIDATE)
        base = yaml.safe_load((HERE / candidate["spec"]["bindings"]["v1CandidatePath"]).read_text())
        base_queries = base["spec"]["planes"]
        runtime_queries = runtime["spec"]["planes"]
        changes = []
        for plane in base_queries:
            for before, after in zip(base_queries[plane]["queries"], runtime_queries[plane]["queries"], strict=True):
                if before != after:
                    changes.append((plane, before["id"]))
        self.assertEqual([("ok-infra", "data-volumes")], changes)

    def test_vm_templates_derive_exact_names(self) -> None:
        self.assertEqual({"cp-disk", "worker-disk"}, vm_data_volume_names(self.virtual_machines()))

    def test_foreign_data_volume_is_filtered(self) -> None:
        items = [
            {"metadata": {"name": "cp-disk"}},
            {"metadata": {"name": "worker-disk"}},
            {"metadata": {"name": "foreign"}},
        ]
        retained = apply_post_filter(items, {"postFilter": DERIVED_RULE}, {"vmDataVolumeTemplateNames": {"cp-disk", "worker-disk"}})
        self.assertEqual(["cp-disk", "worker-disk"], [item["metadata"]["name"] for item in retained])

    def test_missing_vm_template_fails(self) -> None:
        with self.assertRaisesRegex(BindingError, "exactly 2"):
            vm_data_volume_names(self.virtual_machines()[:1])

    def test_grant_rejects_delete_authority(self) -> None:
        now = dt.datetime(2026, 8, 20, 15, 0, tzinfo=dt.timezone.utc)
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "OK141DeleteD0BindingGrant",
            "spec": {
                "state": "GRANTED",
                "grantID": "test",
                "candidateDigest": file_digest(CANDIDATE),
                "notBefore": "2026-08-20T14:55:00Z",
                "notAfter": "2026-08-20T15:10:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "bindingPath": "/private/tmp/ok141-delete-d0-runtime-binding-v2.json",
                "evidencePath": "/private/tmp/ok141-delete-d0-evidence-v2.json",
                "readOnlyAuthorized": True,
                "credentialUseAuthorized": True,
                "secretMetadataReadAuthorized": True,
                "mutationAuthorized": False,
                "deleteAuthorized": True,
                "cleanupAuthorized": False,
                "retryAuthorized": False,
                "rollbackAuthorized": False,
                "outageAuthorized": False,
                "failureInjectionAuthorized": False,
                "publicationAuthorized": False,
            },
        }
        with self.assertRaisesRegex(BindingError, "deleteAuthorized"):
            verify_grant(CANDIDATE, self.write_yaml(grant, "grant.yaml"), now)

    def test_stopped_evidence_records_no_partial_output(self) -> None:
        stopped = yaml.safe_load((HERE / "delete-d0-v1-stopped-evidence.yaml").read_text())["spec"]
        self.assertFalse(stopped["result"]["runtimeBindingWritten"])
        self.assertFalse(stopped["result"]["privateEvidenceWritten"])
        self.assertFalse(stopped["result"]["retryPerformed"])

    def test_publication_candidate_is_bound_and_not_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d0-v2-publication-candidate.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
