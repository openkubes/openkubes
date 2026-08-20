#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

import yaml

from prepare_delete_d0_binding_v1 import (
    BindingError,
    canonical_digest,
    file_digest,
    safe_metadata,
    verify_candidate,
    verify_grant,
)


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d0-binding-candidate-v1.yaml"


class D0BindingTest(unittest.TestCase):
    def write_yaml(self, value: object, name: str) -> Path:
        path = Path(self.temp.name) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_candidate_passes(self) -> None:
        verified = verify_candidate(CANDIDATE)
        self.assertEqual("READY-FOR-EXPLICIT-READ-ONLY-GRANT", verified["spec"]["state"])

    def test_candidate_grants_nothing(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["authorization"]["deleteGranted"] = True
        with self.assertRaisesRegex(BindingError, "grants authority"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_query_profile_change_fails(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["planes"]["ok-shared"]["queries"].pop()
        with self.assertRaisesRegex(BindingError, "query profile"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_non_get_fails(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        candidate["spec"]["planes"]["ok-mgmt"]["queries"][0]["method"] = "DELETE"
        with self.assertRaisesRegex(BindingError, "non-GET"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_unbounded_collection_fails(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        query = candidate["spec"]["planes"]["ok-infra"]["queries"][8]
        query.pop("postFilter")
        with self.assertRaisesRegex(BindingError, "unbounded collection"):
            verify_candidate(self.write_yaml(candidate, "candidate.yaml"))

    def test_secret_values_are_removed(self) -> None:
        retained = safe_metadata({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "bound", "namespace": "argocd", "uid": "u", "resourceVersion": "1"},
            "data": {"token": "forbidden", "server": "forbidden"},
        })
        self.assertEqual(["server", "token"], retained["dataKeys"])
        self.assertNotIn("data", retained)
        self.assertNotIn("forbidden", str(retained))

    def test_grant_template_is_not_granted(self) -> None:
        grant = yaml.safe_load((HERE / "delete-d0-binding-grant-v1.template.yaml").read_text())
        self.assertEqual("TEMPLATE-NOT-GRANTED", grant["spec"]["state"])
        self.assertFalse(any(value for key, value in grant["spec"].items() if key.endswith("Authorized")))

    def test_publication_candidate_is_bound_and_not_authorized(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d0-publication-candidate-v1.yaml").read_text())
        spec = publication["spec"]
        candidate = yaml.safe_load(CANDIDATE.read_text())
        self.assertEqual(file_digest(CANDIDATE), spec["bindings"]["candidateFileDigest"])
        self.assertEqual(canonical_digest(candidate), spec["bindings"]["candidateSemanticDigest"])
        self.assertEqual(9, spec["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in spec["authorization"].items() if key.endswith("Granted")))

    def test_grant_rejects_delete_authority(self) -> None:
        now = dt.datetime(2026, 8, 20, 14, 0, tzinfo=dt.timezone.utc)
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "OK141DeleteD0BindingGrant",
            "spec": {
                "state": "GRANTED",
                "grantID": "test",
                "candidateDigest": "invalid-until-test-patches-file",
                "notBefore": "2026-08-20T13:55:00Z",
                "notAfter": "2026-08-20T14:10:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "bindingPath": "/private/tmp/ok141-delete-d0-runtime-binding-v1.json",
                "evidencePath": "/private/tmp/ok141-delete-d0-evidence-v1.json",
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
        grant["spec"]["candidateDigest"] = file_digest(CANDIDATE)
        with self.assertRaisesRegex(BindingError, "deleteAuthorized"):
            verify_grant(CANDIDATE, self.write_yaml(grant, "grant.yaml"), now)


if __name__ == "__main__":
    unittest.main()
