#!/usr/bin/env python3

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

import yaml

import bounded_delete_d1_v2 as runner


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-execution-candidate-v2.yaml"


class DeleteD1ExecutionV2Test(unittest.TestCase):
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
            "deleteOrder": [{"queryID": query_id, "name": targets[query_id]["name"], "namespace": "argocd", "uid": f"uid-{index}", "resourceVersion": str(index)} for index, query_id in enumerate(runner.EXPECTED_ORDER, start=1)],
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
        path = self.changed(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(runner.D1Error, "grants authority"):
            runner.verify_candidate(path)

    def test_candidate_order_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["deleteOrder"].reverse())
        with self.assertRaisesRegex(runner.D1Error, "delete order"):
            runner.verify_candidate(path)

    def test_ordered_v3_binding_passes(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        _, records = runner.validate_binding(candidate, self.write_binding(self.binding()), dt.datetime.now(dt.timezone.utc))
        self.assertEqual(runner.EXPECTED_ORDER, tuple(record["queryID"] for record in records))

    def test_v2_order_fails(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        value = self.binding()
        value["deleteOrder"][-2:] = reversed(value["deleteOrder"][-2:])
        with self.assertRaisesRegex(runner.D1Error, "order mismatch"):
            runner.validate_binding(candidate, self.write_binding(value), dt.datetime.now(dt.timezone.utc))

    def test_wrong_order_profile_fails(self) -> None:
        candidate = runner.verify_candidate(CANDIDATE)
        value = self.binding()
        value["bindingOrderProfile"] = "wrong"
        with self.assertRaisesRegex(runner.D1Error, "order profile"):
            runner.validate_binding(candidate, self.write_binding(value), dt.datetime.now(dt.timezone.utc))

    def test_delete_payload_has_both_preconditions(self) -> None:
        record = self.binding()["deleteOrder"][0]
        payload = json.loads(runner.V1.delete_payload(record))
        self.assertEqual({"uid": record["uid"], "resourceVersion": record["resourceVersion"]}, payload["preconditions"])

    def test_publication_candidate_is_non_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-execution-v2-publication-candidate.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE), publication["bindings"]["candidateDigest"])
        self.assertEqual(8, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
