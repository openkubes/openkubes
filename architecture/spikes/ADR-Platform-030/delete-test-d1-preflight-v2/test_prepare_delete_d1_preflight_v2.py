#!/usr/bin/env python3

from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_delete_d1_preflight_v2 import (
    EXPECTED_DIGESTS,
    PreflightError,
    V1,
    build_binding,
    canonical_digest,
    file_digest,
    normalized_digest,
    verify_candidate,
    verify_grant,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-preflight-candidate-v2.yaml"
APPLICATIONS = HERE / "../harness/profiles/platform/minimal-observability-v9/applications.yaml"


class DeleteD1PreflightV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.now = dt.datetime(2026, 8, 20, 16, 0, tzinfo=dt.timezone.utc)
        documents = {item["metadata"]["name"]: item for item in yaml.safe_load_all(APPLICATIONS.read_text())}
        self.live = {}
        shared = {}
        for index, query_id in enumerate(V1.APP_IDS, start=1):
            name = V1.APP_NAMES[query_id]
            app = copy.deepcopy(documents[name])
            app["metadata"].update({"uid": f"app-{index}", "resourceVersion": "200", "generation": 20, "finalizers": []})
            app["status"] = {"sync": {"status": "Synced"}, "health": {"status": "Healthy"}}
            if name != "disposable-ok141-observability-core":
                del app["spec"]["source"]["directory"]["recurse"]
            self.live[query_id] = app
            shared[query_id] = [{
                "name": name, "namespace": "argocd", "uid": f"app-{index}",
                "resourceVersion": "100", "generation": 10, "finalizers": [], "deletionTimestamp": None,
                "application": {"project": "openkubes-disposable", "sync": "Synced", "health": "Healthy", "automated": True},
            }]
        self.live["project-applications"] = {"items": [self.live[query_id] for query_id in V1.APP_IDS]}
        self.live["app-project"] = {"metadata": {"name": "openkubes-disposable", "namespace": "argocd", "uid": "project-1", "resourceVersion": "100", "finalizers": []}}
        self.live["registration-secret"] = {
            "metadata": {"name": "disposable-ok141-cluster", "namespace": "argocd", "uid": "secret-1", "resourceVersion": "100", "finalizers": [], "labels": {"argocd.argoproj.io/secret-type": "cluster"}},
            "data": {"server": base64.b64encode(b"https://target.invalid").decode(), "name": base64.b64encode(b"disposable-ok141").decode()},
        }
        for query_id in V1.APP_IDS:
            self.live[query_id]["spec"]["destination"] = {"name": "disposable-ok141", "namespace": "ok-observability"}
        shared["project-applications"] = [copy.deepcopy(shared[query_id][0]) for query_id in V1.APP_IDS]
        shared["app-project"] = [{"name": "openkubes-disposable", "namespace": "argocd", "uid": "project-1", "resourceVersion": "100", "finalizers": [], "deletionTimestamp": None}]
        shared["registration-secret"] = [{"name": "disposable-ok141-cluster", "namespace": "argocd", "uid": "secret-1", "resourceVersion": "100", "finalizers": [], "deletionTimestamp": None, "dataKeys": ["name", "server"]}]
        self.d0 = {
            "format": "ok141-delete-d0-runtime-binding/v3",
            "candidateDigest": V1.EXPECTED_D0_CANDIDATE,
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
        return {"spec": {
            "state": "GRANTED", "grantID": "test", "candidateDigest": file_digest(CANDIDATE),
            "d0BindingDigest": file_digest(d0_path), "notBefore": "2026-08-20T15:55:00Z",
            "notAfter": "2026-08-20T16:05:00Z", "maximumRuns": 1, "consumed": False,
            "bindingPath": "/private/tmp/ok141-delete-d1-runtime-binding-v2.json",
            "evidencePath": "/private/tmp/ok141-delete-d1-preflight-evidence-v2.json",
            "readOnlyAuthorized": True, "credentialUseAuthorized": True, "secretContentReadAuthorized": True,
            "mutationAuthorized": False, "deleteAuthorized": False, "cleanupAuthorized": False,
            "retryAuthorized": False, "rollbackAuthorized": False, "publicationAuthorized": False,
            "outageAuthorized": False, "failureInjectionAuthorized": False,
        }}

    def test_candidate_passes(self) -> None:
        self.assertEqual("NO-GO", verify_candidate(CANDIDATE)[0]["spec"]["authorization"]["decision"])

    def test_missing_false_default_normalizes_to_expected(self) -> None:
        for query_id in V1.APP_IDS:
            app = self.live[query_id]
            self.assertEqual(EXPECTED_DIGESTS[app["metadata"]["name"]], normalized_digest(app))

    def test_true_recurse_fails_semantic_check(self) -> None:
        self.live["application-alerting"]["spec"]["source"]["directory"]["recurse"] = True
        with self.assertRaisesRegex(PreflightError, "semantics mismatch"):
            build_binding(verify_candidate(CANDIDATE)[0], self.d0, self.live, self.now)

    def test_resource_version_and_generation_advance_are_rebound(self) -> None:
        binding = build_binding(verify_candidate(CANDIDATE)[0], self.d0, self.live, self.now)
        application_records = binding["deleteOrder"][:3]
        self.assertEqual({"200"}, {item["resourceVersion"] for item in application_records})
        self.assertEqual(3, len(binding["applicationSemanticDigests"]))

    def test_uid_drift_fails(self) -> None:
        self.live["application-core"]["metadata"]["uid"] = "different"
        with self.assertRaisesRegex(PreflightError, "immutable identity"):
            build_binding(verify_candidate(CANDIDATE)[0], self.d0, self.live, self.now)

    def test_app_project_resource_version_stays_strict(self) -> None:
        self.live["app-project"]["metadata"]["resourceVersion"] = "101"
        with self.assertRaisesRegex(PreflightError, "app-project differs"):
            build_binding(verify_candidate(CANDIDATE)[0], self.d0, self.live, self.now)

    def test_extra_project_application_fails(self) -> None:
        self.live["project-applications"]["items"].append({"metadata": {"name": "extra"}, "spec": {"project": "openkubes-disposable"}})
        with self.assertRaisesRegex(PreflightError, "membership"):
            build_binding(verify_candidate(CANDIDATE)[0], self.d0, self.live, self.now)

    def test_fresh_grant_passes(self) -> None:
        d0_path = self.write_json(self.d0, "d0.json")
        grant_path = self.write_yaml(self.grant(d0_path), "grant.yaml")
        verify_grant(CANDIDATE, grant_path, d0_path, self.now)

    def test_publication_candidate_is_bound(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-preflight-v2-publication-candidate.yaml").read_text())["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), publication["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), publication["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
