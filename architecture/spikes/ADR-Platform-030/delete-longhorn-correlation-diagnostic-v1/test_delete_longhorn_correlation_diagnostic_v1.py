#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import yaml

from run_delete_longhorn_correlation_diagnostic_v1 import (
    DiagnosticError,
    canonical_digest,
    correlate,
    file_digest,
    verify_candidate,
    verify_grant,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-longhorn-correlation-diagnostic-candidate-v1.yaml"


class LonghornCorrelationDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_yaml(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    @staticmethod
    def pvs() -> list[dict]:
        return [
            {"metadata": {"name": "pv-a"}, "spec": {"claimRef": {"namespace": "disposable-ok141", "name": "pvc-a"}, "csi": {"volumeHandle": "handle-a"}}},
            {"metadata": {"name": "pv-b"}, "spec": {"claimRef": {"namespace": "disposable-ok141", "name": "pvc-b"}, "csi": {"volumeHandle": "handle-b"}}},
        ]

    @staticmethod
    def status_correlated_volumes() -> list[dict]:
        return [
            {"metadata": {"name": "lh-a"}, "spec": {"fromBackup": ""}, "status": {"state": "attached", "robustness": "degraded", "kubernetesStatus": {"namespace": "disposable-ok141", "pvName": "pv-a", "pvcName": "pvc-a"}}},
            {"metadata": {"name": "lh-b"}, "spec": {"fromBackup": ""}, "status": {"state": "attached", "robustness": "degraded", "kubernetesStatus": {"namespace": "disposable-ok141", "pvName": "pv-b", "pvcName": "pvc-b"}}},
        ]

    def test_candidate_passes(self) -> None:
        self.assertEqual("NO-GO", verify_candidate(CANDIDATE)["spec"]["authorization"]["decision"])

    def test_candidate_grants_nothing(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["authorization"]["deleteGranted"] = True
        with self.assertRaisesRegex(DiagnosticError, "grants authority"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_status_tuple_correlates_when_names_do_not(self) -> None:
        result = correlate(self.pvs(), self.status_correlated_volumes())
        self.assertEqual(0, result["matchCounts"]["volumeHandleToMetadataName"])
        self.assertEqual(0, result["matchCounts"]["pvNameToMetadataName"])
        self.assertEqual(2, result["matchCounts"]["kubernetesStatusTuple"])
        self.assertEqual("ONE-EXACT-CORRELATION", result["verdict"])
        self.assertFalse(result["rawNamesRetained"])

    def test_equivalent_name_correlations_are_reported(self) -> None:
        volumes = self.status_correlated_volumes()
        volumes[0]["metadata"]["name"] = "pv-a"
        volumes[1]["metadata"]["name"] = "pv-b"
        result = correlate(self.pvs(), volumes)
        self.assertEqual("MULTIPLE-EQUIVALENT-CORRELATIONS", result["verdict"])

    def test_no_correlation_fails_closed_in_result(self) -> None:
        volumes = self.status_correlated_volumes()
        for volume in volumes:
            volume["status"]["kubernetesStatus"]["namespace"] = "other"
        result = correlate(self.pvs(), volumes)
        self.assertEqual("NO-EXACT-TWO-WAY-CORRELATION", result["verdict"])

    def test_wrong_provider_pv_count_fails(self) -> None:
        with self.assertRaisesRegex(DiagnosticError, "expected 2"):
            correlate(self.pvs()[:1], self.status_correlated_volumes())

    def test_grant_rejects_delete_authority(self) -> None:
        now = dt.datetime(2026, 8, 20, 15, 0, tzinfo=dt.timezone.utc)
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "OK141DeleteLonghornCorrelationDiagnosticGrant",
            "spec": {
                "state": "GRANTED", "grantID": "test", "candidateDigest": file_digest(CANDIDATE),
                "notBefore": "2026-08-20T14:55:00Z", "notAfter": "2026-08-20T15:10:00Z",
                "maximumRuns": 1, "consumed": False,
                "evidencePath": "/private/tmp/ok141-delete-longhorn-correlation-diagnostic-v1-evidence.json",
                "readOnlyAuthorized": True, "credentialUseAuthorized": True,
                "mutationAuthorized": False, "deleteAuthorized": True, "cleanupAuthorized": False,
                "retryAuthorized": False, "publicationAuthorized": False, "failureInjectionAuthorized": False,
            },
        }
        with self.assertRaisesRegex(DiagnosticError, "deleteAuthorized"):
            verify_grant(CANDIDATE, self.write_yaml(grant, "grant.yaml"), now)

    def test_stopped_evidence_has_no_partial_output(self) -> None:
        stopped = yaml.safe_load((HERE / "delete-d0-v2-stopped-evidence.yaml").read_text())["spec"]
        self.assertFalse(stopped["result"]["runtimeBindingWritten"])
        self.assertFalse(stopped["result"]["privateEvidenceWritten"])
        self.assertFalse(stopped["result"]["retryPerformed"])

    def test_publication_candidate_is_bound_and_not_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-longhorn-correlation-publication-candidate-v1.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
