#!/usr/bin/env python3

from __future__ import annotations

import copy
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

import prepare_delete_d1_preflight_v3 as runner


HERE = Path(__file__).resolve().parent
CANDIDATE = HERE / "delete-d1-preflight-candidate-v3.yaml"


class D1PreflightV3Test(unittest.TestCase):
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

    def test_candidate_passes(self) -> None:
        self.assertEqual("READY-FOR-EXPLICIT-READ-ONLY-GRANT", runner.verify_candidate(CANDIDATE)[0]["spec"]["state"])

    def test_order_change_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["bindingOrder"].reverse())
        with self.assertRaisesRegex(runner.PreflightError, "binding order"):
            runner.verify_candidate(path)

    def test_delete_authority_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["authorization"].update(deleteGranted=True))
        with self.assertRaisesRegex(runner.PreflightError, "grants authority"):
            runner.verify_candidate(path)

    def test_v2_reinterpretation_fails(self) -> None:
        path = self.changed(lambda value: value["spec"]["assertions"].update(oldV2DigestReinterpreted=True))
        with self.assertRaisesRegex(runner.PreflightError, "reinterpretation"):
            runner.verify_candidate(path)

    def test_build_binding_reorders_exactly(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        old = [{"queryID": query_id} for query_id in (
            "application-dashboards", "application-alerting", "application-core",
            "app-project", "registration-secret",
        )]
        base = {"format": "old", "deleteOrder": old}
        with mock.patch.object(runner.V2, "build_binding", return_value=copy.deepcopy(base)):
            binding = runner.build_binding(candidate, {}, {}, dt.datetime.now(dt.timezone.utc))
        self.assertEqual(runner.EXPECTED_ORDER, tuple(item["queryID"] for item in binding["deleteOrder"]))
        self.assertEqual("ok141-delete-d1-runtime-binding/v3", binding["format"])

    def test_missing_record_fails(self) -> None:
        candidate = yaml.safe_load(CANDIDATE.read_text())
        base = {"deleteOrder": [{"queryID": query_id} for query_id in runner.EXPECTED_ORDER[:-1]]}
        with mock.patch.object(runner.V2, "build_binding", return_value=base):
            with self.assertRaisesRegex(runner.PreflightError, "membership"):
                runner.build_binding(candidate, {}, {}, dt.datetime.now(dt.timezone.utc))

    def test_publication_candidate_is_non_authorizing(self) -> None:
        publication = yaml.safe_load((HERE / "delete-d1-preflight-v3-publication-candidate.yaml").read_text())["spec"]
        self.assertEqual(runner.file_digest(CANDIDATE), publication["bindings"]["candidateDigest"])
        self.assertEqual(7, publication["bindings"]["offlineTestsPassed"])
        self.assertFalse(any(value for key, value in publication["authorization"].items() if key.endswith("Granted")))


if __name__ == "__main__":
    unittest.main()
