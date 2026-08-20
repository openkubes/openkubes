#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_delete_d0_binding_v3 import (
    BindingError,
    LONGHORN_RULE,
    amended_runtime_candidate,
    apply_post_filter,
    canonical_digest,
    derive_provider_pv_rows,
    file_digest,
    safe_item,
    verify_candidate,
    verify_grant,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d0-binding-candidate-v3.yaml"


class DeleteD0V3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_yaml(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    @staticmethod
    def pvs_without_kind() -> list[dict]:
        return [
            {"metadata": {"name": "pv-a"}, "spec": {"claimRef": {"namespace": "disposable-ok141", "name": "pvc-a", "uid": "claim-a"}, "csi": {"volumeHandle": "pv-a"}, "persistentVolumeReclaimPolicy": "Retain", "storageClassName": "ok-storage-block"}, "status": {"phase": "Bound"}},
            {"metadata": {"name": "pv-b"}, "spec": {"claimRef": {"namespace": "disposable-ok141", "name": "pvc-b", "uid": "claim-b"}, "csi": {"volumeHandle": "pv-b"}, "persistentVolumeReclaimPolicy": "Retain", "storageClassName": "ok-storage-block"}, "status": {"phase": "Bound"}},
        ]

    @staticmethod
    def longhorn_volumes() -> list[dict]:
        return [
            {"metadata": {"name": "pv-a"}, "spec": {"fromBackup": ""}, "status": {"state": "attached", "robustness": "degraded", "kubernetesStatus": {"namespace": "disposable-ok141", "pvName": "pv-a", "pvcName": "pvc-a"}}},
            {"metadata": {"name": "pv-b"}, "spec": {"fromBackup": ""}, "status": {"state": "attached", "robustness": "degraded", "kubernetesStatus": {"namespace": "disposable-ok141", "pvName": "pv-b", "pvcName": "pvc-b"}}},
        ]

    def test_candidate_passes(self) -> None:
        candidate, runtime = verify_candidate(CANDIDATE)
        self.assertEqual("NO-GO", candidate["spec"]["authorization"]["decision"])
        self.assertEqual("sha256:f8dbcf6195712fdac4acfa5ff5bbc2eb8694f8c1f6436e6c400758cfa5888853", runtime["spec"]["tool"]["queryProfileDigest"])

    def test_candidate_grants_nothing(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["authorization"]["deleteGranted"] = True
        with self.assertRaisesRegex(BindingError, "grants authority"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_only_longhorn_filter_changes_from_v2_runtime(self) -> None:
        candidate, runtime = verify_candidate(CANDIDATE)
        v2_path = (HERE / candidate["spec"]["bindings"]["v2CandidatePath"]).resolve()
        v2_candidate = yaml.safe_load(v2_path.read_text())
        import prepare_delete_d0_binding_v3 as module
        v2_runtime = module.V2.amended_runtime_candidate(v2_candidate, v2_path)
        changes = []
        for plane in v2_runtime["spec"]["planes"]:
            for before, after in zip(v2_runtime["spec"]["planes"][plane]["queries"], runtime["spec"]["planes"][plane]["queries"], strict=True):
                if before != after:
                    changes.append((plane, before["id"]))
        self.assertEqual([("ok-infra", "provider-longhorn-volumes")], changes)

    def test_raw_pv_rows_do_not_require_kind(self) -> None:
        rows = derive_provider_pv_rows(self.pvs_without_kind())
        self.assertEqual(2, len(rows))
        self.assertEqual({"pv-a", "pv-b"}, {row["handle"] for row in rows})

    def test_safe_pv_storage_does_not_require_kind(self) -> None:
        retained = safe_item(self.pvs_without_kind()[0], "provider-pvs")
        self.assertEqual("pv-a", retained["storage"]["volumeHandle"])
        self.assertEqual("Retain", retained["storage"]["reclaimPolicy"])

    def test_exact_longhorn_equality_matches_two(self) -> None:
        rows = derive_provider_pv_rows(self.pvs_without_kind())
        retained = apply_post_filter(self.longhorn_volumes(), {"postFilter": LONGHORN_RULE}, {"providerPVRows": rows})
        self.assertEqual(2, len(retained))

    def test_longhorn_tuple_mismatch_fails_closed(self) -> None:
        rows = derive_provider_pv_rows(self.pvs_without_kind())
        volumes = self.longhorn_volumes()
        volumes[0]["status"]["kubernetesStatus"]["pvcName"] = "wrong"
        retained = apply_post_filter(volumes, {"postFilter": LONGHORN_RULE}, {"providerPVRows": rows})
        self.assertEqual(1, len(retained))

    def test_incomplete_pv_identity_fails(self) -> None:
        pvs = self.pvs_without_kind()
        del pvs[0]["spec"]["csi"]["volumeHandle"]
        with self.assertRaisesRegex(BindingError, "incomplete"):
            derive_provider_pv_rows(pvs)

    def test_grant_rejects_delete_authority(self) -> None:
        now = dt.datetime(2026, 8, 20, 16, 0, tzinfo=dt.timezone.utc)
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "OK141DeleteD0BindingGrant",
            "spec": {
                "state": "GRANTED", "grantID": "test", "candidateDigest": file_digest(CANDIDATE),
                "notBefore": "2026-08-20T15:55:00Z", "notAfter": "2026-08-20T16:10:00Z",
                "maximumRuns": 1, "consumed": False,
                "bindingPath": "/private/tmp/ok141-delete-d0-runtime-binding-v3.json",
                "evidencePath": "/private/tmp/ok141-delete-d0-evidence-v3.json",
                "readOnlyAuthorized": True, "credentialUseAuthorized": True, "secretMetadataReadAuthorized": True,
                "mutationAuthorized": False, "deleteAuthorized": True, "cleanupAuthorized": False,
                "retryAuthorized": False, "rollbackAuthorized": False, "outageAuthorized": False,
                "failureInjectionAuthorized": False, "publicationAuthorized": False,
            },
        }
        with self.assertRaisesRegex(BindingError, "deleteAuthorized"):
            verify_grant(CANDIDATE, self.write_yaml(grant, "grant.yaml"), now)

    def test_publication_candidate_is_bound_and_not_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d0-v3-publication-candidate.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(10, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
