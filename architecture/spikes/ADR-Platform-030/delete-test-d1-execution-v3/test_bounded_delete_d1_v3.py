#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import yaml

import bounded_delete_d1_v3 as runner


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-execution-candidate-v3.yaml"


class DeleteD1ExecutionV3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def changed(self, mutate) -> Path:
        value = yaml.safe_load(CANDIDATE.read_text())
        mutate(value)
        path = Path(self.temp.name) / "candidate.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def binding(self) -> dict:
        v3 = yaml.safe_load((HERE / "../delete-test-d1-preflight-v3/delete-d1-preflight-candidate-v3.yaml").read_text())
        targets = {item["queryID"]: item for item in yaml.safe_load(CANDIDATE.read_text())["spec"]["deleteOrder"]}
        return {
            "format": "ok141-delete-d1-runtime-binding/v3",
            "state": "PASS-D1-PREFLIGHT-PRIVATE-BOUND-NO-GO",
            "candidateDigest": runner.canonical_digest(v3),
            "bindingOrderProfile": "ok141-delete-d1-order/v1",
            "expiresAt": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=4)).isoformat(),
            "deleteOrder": [{"queryID": q, "name": targets[q]["name"], "namespace": "argocd", "uid": f"uid-{i}", "resourceVersion": str(i)} for i, q in enumerate(runner.EXPECTED_ORDER, start=1)],
            "mutationPerformed": False, "deletePerformed": False,
        }

    def write_binding(self, value: dict) -> Path:
        path = Path(self.temp.name) / "binding.json"
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def test_candidate_passes(self) -> None:
        self.assertEqual("OFFLINE-PREPARED-BLOCKED-NO-GO", runner.verify_candidate(CANDIDATE)["spec"]["state"])

    def test_candidate_cannot_grant_delete(self) -> None:
        path = self.changed(lambda v: v["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(runner.D1Error, "grants authority"):
            runner.verify_candidate(path)

    def test_order_change_fails(self) -> None:
        path = self.changed(lambda v: v["spec"]["deleteOrder"].reverse())
        with self.assertRaisesRegex(runner.D1Error, "delete targets reinterpreted|delete order"):
            runner.verify_candidate(path)

    def test_target_change_fails(self) -> None:
        path = self.changed(lambda v: v["spec"]["deleteOrder"][0].update(name="wrong"))
        with self.assertRaisesRegex(runner.D1Error, "delete targets reinterpreted"):
            runner.verify_candidate(path)

    def test_uid_is_immutable_anchor_and_live_rv_is_used(self) -> None:
        record = self.binding()["deleteOrder"][0]
        current = {"metadata": {"name": record["name"], "namespace": record["namespace"], "uid": record["uid"], "resourceVersion": "999"}}
        live, changed = runner.live_delete_record(current, record, True)
        self.assertTrue(changed)
        self.assertEqual(record["uid"], live["uid"])
        self.assertEqual("999", live["resourceVersion"])
        payload = json.loads(runner.V1.delete_payload(live))
        self.assertEqual({"uid": record["uid"], "resourceVersion": "999"}, payload["preconditions"])

    def test_uid_change_fails(self) -> None:
        record = self.binding()["deleteOrder"][0]
        current = {"metadata": {"name": record["name"], "namespace": record["namespace"], "uid": "replacement", "resourceVersion": "999"}}
        with self.assertRaisesRegex(runner.D1Error, "immutable identity"):
            runner.live_delete_record(current, record, True)

    def test_finalizer_fails(self) -> None:
        record = self.binding()["deleteOrder"][0]
        current = {"metadata": {"name": record["name"], "namespace": record["namespace"], "uid": record["uid"], "resourceVersion": "999", "finalizers": ["resources-finalizer.argocd.argoproj.io"]}}
        with self.assertRaisesRegex(runner.D1Error, "finalizer"):
            runner.live_delete_record(current, record, True)

    def test_deletion_timestamp_fails(self) -> None:
        record = self.binding()["deleteOrder"][0]
        current = {"metadata": {"name": record["name"], "namespace": record["namespace"], "uid": record["uid"], "resourceVersion": "999", "deletionTimestamp": "now"}}
        with self.assertRaisesRegex(runner.D1Error, "already deleting"):
            runner.live_delete_record(current, record, True)

    def test_old_v2_candidate_not_reinterpreted(self) -> None:
        self.assertEqual(runner.EXPECTED_V2_CANDIDATE, runner.file_digest(HERE / "../delete-test-d1-execution-v2/delete-d1-execution-candidate-v2.yaml"))

    def test_publication_candidate_is_non_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-execution-v3-publication-candidate.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE), publication["bindings"]["candidateDigest"])
        self.assertEqual(10, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
