#!/usr/bin/env python3

from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

import bounded_delete_d1_v1 as runner


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-execution-candidate-v1.yaml"


class DeleteD1ExecutionV1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def changed_candidate(self, mutate) -> Path:
        value = yaml.safe_load(CANDIDATE.read_text())
        mutate(value)
        path = Path(self.temp.name) / "candidate.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def binding(self, expires: dt.datetime | None = None) -> dict:
        candidate = yaml.safe_load((HERE / "../delete-test-d1-preflight-v2/delete-d1-preflight-candidate-v2.yaml").read_text())
        names = {item["queryID"]: item for item in yaml.safe_load(CANDIDATE.read_text())["spec"]["deleteOrder"]}
        return {
            "format": "ok141-delete-d1-runtime-binding/v2",
            "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
            "candidateDigest": runner.canonical_digest(candidate),
            "expiresAt": (expires or dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=4)).isoformat(),
            "deleteOrder": [{
                "queryID": query_id,
                "name": names[query_id]["name"],
                "namespace": "argocd",
                "uid": f"uid-{index}",
                "resourceVersion": str(index),
            } for index, query_id in enumerate(runner.EXPECTED_QUERY_IDS, start=1)],
            "mutationPerformed": False,
            "deletePerformed": False,
        }

    def write_binding(self, value: dict) -> Path:
        path = Path(self.temp.name) / "binding.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def test_candidate_passes(self) -> None:
        self.assertEqual("OFFLINE-PREPARED-BLOCKED-NO-GO", runner.verify_candidate(CANDIDATE)["spec"]["state"])

    def test_candidate_cannot_grant_delete(self) -> None:
        path = self.changed_candidate(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(runner.D1Error, "grants authority"):
            runner.verify_candidate(path)

    def test_delete_order_change_fails(self) -> None:
        path = self.changed_candidate(lambda value: value["spec"]["deleteOrder"].reverse())
        with self.assertRaisesRegex(runner.D1Error, "delete order"):
            runner.verify_candidate(path)

    def test_binding_passes(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        _, records = runner.validate_binding(candidate, self.write_binding(self.binding()), dt.datetime.now(dt.timezone.utc))
        self.assertEqual(runner.EXPECTED_QUERY_IDS, tuple(record["queryID"] for record in records))

    def test_expired_binding_fails(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        with self.assertRaisesRegex(runner.D1Error, "expired"):
            runner.validate_binding(candidate, self.write_binding(self.binding(expired)), dt.datetime.now(dt.timezone.utc))

    def test_binding_target_change_fails(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        value = self.binding()
        value["deleteOrder"][0]["name"] = "wrong"
        with self.assertRaisesRegex(runner.D1Error, "target mismatch"):
            runner.validate_binding(candidate, self.write_binding(value), dt.datetime.now(dt.timezone.utc))

    def test_delete_options_bind_both_preconditions(self) -> None:
        record = self.binding()["deleteOrder"][0]
        payload = json.loads(runner.delete_payload(record))
        self.assertEqual({"uid": record["uid"], "resourceVersion": record["resourceVersion"]}, payload["preconditions"])
        self.assertEqual("Background", payload["propagationPolicy"])

    def test_application_finalizer_fails(self) -> None:
        record = self.binding()["deleteOrder"][0]
        value = {"metadata": {**{key: record[key] for key in ("name", "namespace", "uid", "resourceVersion")}, "finalizers": ["resources-finalizer.argocd.argoproj.io"]}}
        with self.assertRaisesRegex(runner.D1Error, "finalizer"):
            runner.assert_current_identity(value, record, True)

    def test_publication_candidate_is_non_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-execution-publication-candidate-v1.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE), publication["bindings"]["candidateDigest"])
        self.assertEqual(9, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
