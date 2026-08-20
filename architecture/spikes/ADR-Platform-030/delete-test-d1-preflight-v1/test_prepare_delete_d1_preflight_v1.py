#!/usr/bin/env python3

from __future__ import annotations

import base64
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_delete_d1_preflight_v1 import (
    APP_IDS,
    APP_NAMES,
    PreflightError,
    build_binding,
    canonical_digest,
    file_digest,
    verify_candidate,
    verify_grant,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-preflight-candidate-v1.yaml"


def metadata(name: str, uid: str) -> dict:
    return {"name": name, "namespace": "argocd", "uid": uid, "resourceVersion": "100", "finalizers": []}


class DeleteD1PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.now = dt.datetime(2026, 8, 20, 16, 0, tzinfo=dt.timezone.utc)
        self.apps = {}
        for index, query_id in enumerate(APP_IDS, start=1):
            self.apps[query_id] = {
                "metadata": metadata(APP_NAMES[query_id], f"app-{index}"),
                "spec": {"project": "openkubes-disposable", "destination": {"server": "https://target.invalid", "namespace": "ok-observability"}},
                "status": {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}},
            }
        self.live = {
            **self.apps,
            "project-applications": {"items": list(self.apps.values())},
            "app-project": {"metadata": metadata("openkubes-disposable", "project-1")},
            "registration-secret": {
                "metadata": {**metadata("disposable-ok141-cluster", "secret-1"), "labels": {"argocd.argoproj.io/secret-type": "cluster"}},
                "data": {
                    "server": base64.b64encode(b"https://target.invalid").decode(),
                    "name": base64.b64encode(b"disposable-ok141").decode(),
                    "config": base64.b64encode(b'{"bearerToken":"not-retained"}').decode(),
                },
            },
        }
        shared = {}
        for query_id in APP_IDS:
            shared[query_id] = [{**metadata(APP_NAMES[query_id], self.apps[query_id]["metadata"]["uid"])}]
        shared["project-applications"] = [{**metadata(APP_NAMES[query_id], self.apps[query_id]["metadata"]["uid"])} for query_id in APP_IDS]
        shared["app-project"] = [{**metadata("openkubes-disposable", "project-1")}]
        shared["registration-secret"] = [{**metadata("disposable-ok141-cluster", "secret-1"), "dataKeys": ["config", "name", "server"]}]
        self.d0 = {
            "format": "ok141-delete-d0-runtime-binding/v3",
            "candidateDigest": "sha256:771c09a760940afa8c04a26a79e3e921c11d87d96ae949c1781f4fd7c846074b",
            "expiresAt": "2026-08-20T16:05:00+00:00",
            "planes": {"ok-shared": shared},
            "mutationPerformed": False,
            "deletePerformed": False,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_json(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        return path

    def write_yaml(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def grant(self, d0_path: Path) -> dict:
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "OK141DeleteD1PreflightGrant",
            "spec": {
                "state": "GRANTED", "grantID": "test", "candidateDigest": file_digest(CANDIDATE),
                "d0BindingDigest": file_digest(d0_path), "notBefore": "2026-08-20T15:55:00Z",
                "notAfter": "2026-08-20T16:05:00Z", "maximumRuns": 1, "consumed": False,
                "bindingPath": "/private/tmp/ok141-delete-d1-runtime-binding-v1.json",
                "evidencePath": "/private/tmp/ok141-delete-d1-preflight-evidence-v1.json",
                "readOnlyAuthorized": True, "credentialUseAuthorized": True, "secretContentReadAuthorized": True,
                "mutationAuthorized": False, "deleteAuthorized": False, "cleanupAuthorized": False,
                "retryAuthorized": False, "rollbackAuthorized": False, "publicationAuthorized": False,
                "outageAuthorized": False, "failureInjectionAuthorized": False,
            },
        }

    def test_candidate_passes(self) -> None:
        self.assertEqual("NO-GO", verify_candidate(CANDIDATE)["spec"]["authorization"]["decision"])

    def test_exact_target_correlation_passes_without_retaining_endpoint(self) -> None:
        binding = build_binding(verify_candidate(CANDIDATE), self.d0, self.live, self.now)
        self.assertEqual(5, len(binding["deleteOrder"]))
        self.assertTrue(binding["targetIdentityDigest"].startswith("sha256:"))
        self.assertNotIn("target.invalid", json.dumps(binding))
        self.assertFalse(binding["secretContentRetained"])

    def test_target_mismatch_fails(self) -> None:
        self.live["application-core"]["spec"]["destination"]["server"] = "https://wrong.invalid"
        with self.assertRaisesRegex(PreflightError, "target mismatch"):
            build_binding(verify_candidate(CANDIDATE), self.d0, self.live, self.now)

    def test_finalizer_fails(self) -> None:
        self.live["application-core"]["metadata"]["finalizers"] = ["resources-finalizer.argocd.argoproj.io"]
        with self.assertRaisesRegex(PreflightError, "finalizer"):
            build_binding(verify_candidate(CANDIDATE), self.d0, self.live, self.now)

    def test_extra_project_application_fails(self) -> None:
        extra = {"metadata": metadata("extra", "extra-1"), "spec": {"project": "openkubes-disposable"}}
        self.live["project-applications"]["items"].append(extra)
        with self.assertRaisesRegex(PreflightError, "membership"):
            build_binding(verify_candidate(CANDIDATE), self.d0, self.live, self.now)

    def test_d0_metadata_drift_fails(self) -> None:
        self.live["application-alerting"]["metadata"]["resourceVersion"] = "101"
        with self.assertRaisesRegex(PreflightError, "differs from D0"):
            build_binding(verify_candidate(CANDIDATE), self.d0, self.live, self.now)

    def test_grant_passes_with_fresh_d0(self) -> None:
        d0_path = self.write_json(self.d0, "d0.json")
        grant_path = self.write_yaml(self.grant(d0_path), "grant.yaml")
        verify_grant(CANDIDATE, grant_path, d0_path, self.now)

    def test_expired_d0_fails(self) -> None:
        self.d0["expiresAt"] = "2026-08-20T15:59:59+00:00"
        d0_path = self.write_json(self.d0, "d0.json")
        grant_path = self.write_yaml(self.grant(d0_path), "grant.yaml")
        with self.assertRaisesRegex(PreflightError, "expired"):
            verify_grant(CANDIDATE, grant_path, d0_path, self.now)

    def test_publication_candidate_is_bound_and_not_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-preflight-publication-candidate-v1.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
