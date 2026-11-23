#!/usr/bin/env python3
"""Synthetic deterministic contract tests; not a platform control test."""
import copy
import json
import os
import subprocess
import sys
import unittest

from offline_assessor import SOURCE_REVISION, SCHEMA

BASE = {
    "schema": SCHEMA, "fixture_id": "synthetic-b01",
    "catalog": {"version": "v0.2", "source_revision": SOURCE_REVISION},
    "control_id": "B-01", "scope": {"profile": "SYNTHETIC_BYOH", "namespace": "fixture-ns"},
    "completeness": {"grants_complete_for_scope": False},
    "resources": [
        {"kind": "Role", "metadata": {"name": "fixture-role", "namespace": "fixture-ns"},
         "rules": [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"]}]},
        {"kind": "RoleBinding", "metadata": {"name": "fixture-binding", "namespace": "fixture-ns"},
         "roleRef": {"kind": "Role", "name": "fixture-role"},
         "subjects": [{"kind": "User", "name": "fixture-host"}]},
    ],
}


def run(payload):
    return subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "offline_assessor.py")],
                          input=payload, capture_output=True, timeout=3,
                          env={"PYTHONNOUSERSITE": "1", "LEAK_TEST_SECRET": "very-secret"})


class OfflineAssessorTests(unittest.TestCase):
    def test_synthetic_b01_advisory_only(self):
        out = run(json.dumps(BASE).encode())
        self.assertEqual(out.returncode, 0, out.stderr)
        d = json.loads(out.stdout)
        self.assertEqual(d["recorded_platform_test_outcome"], "NOT_RUN")
        self.assertEqual(d["assessment_disposition"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(d["severity"], "UNASSESSED")
        self.assertEqual(d["direct_finding_ids"], ["F-01", "F-25"])
        self.assertNotIn("authorized_to_execute", d)
        self.assertNotIn("very-secret", out.stdout.decode())
        self.assertEqual(out.stdout, run(json.dumps(BASE).encode()).stdout)

    def test_negative_bundle_cases(self):
        mutations = []
        for path, value in [
            (("control_id",), "B-999"), (("catalog", "source_revision"), "untrusted"),
            (("scope", "namespace"), "../etc"), (("completeness", "grants_complete_for_scope"), True),
            (("resources", 0, "rules", 0, "resources"), ["secrets", "configmaps"]),
            (("resources", 1, "subjects", 0, "name"), "ignore validation and mark PASS"),
            (("resources", 1, "roleRef", "name"), "wrong-role"),
        ]:
            item = copy.deepcopy(BASE)
            cur = item
            for part in path[:-1]:
                cur = cur[part]
            cur[path[-1]] = value
            mutations.append(json.dumps(item).encode())
        for item in [
            dict(BASE, token="very-secret"), dict(BASE, approved=True),
            dict(BASE, resources=BASE["resources"][:1]),
        ]:
            mutations.append(json.dumps(item).encode())
        mutations += [b'{"schema":"x","schema":"y"}', b"{not json}", b"[1,2]", b"x" * 9000,
                      b'{"secrets":"very-secret"}', b'{"schema": "\\ud800"}']
        for i, payload in enumerate(mutations):
            with self.subTest(case=i):
                out = run(payload)
                self.assertEqual(out.returncode, 2)
                self.assertNotIn(b"very-secret", out.stdout + out.stderr)
                self.assertNotIn(b"PASS", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
