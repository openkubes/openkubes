import copy
import datetime as dt
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


OBS = load("observe_recovery_snapshot_attempt_test", HERE / "observe_recovery_snapshot_attempt_v1.py")
MAT = load("materialize_recovery_binding_attempt_test", HERE / "materialize_recovery_binding_attempt_v1.py")
CLEAN = load("bounded_recovery_cleanup_attempt_test", HERE / "bounded_recovery_cleanup_attempt_v1.py")
SNAPSHOT = HERE / "recovery-snapshot-attempt-r0-v4-20260814-01.yaml"
CLEANUP = HERE / "recovery-cleanup-candidate-r0-v4-20260814-01.yaml"


class ReusableRecoveryAttemptTests(unittest.TestCase):
    def write_yaml(self, directory, name, value):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        return path

    def write_evidence(self, directory, value):
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(value, sort_keys=True))
        path.chmod(0o600)
        return path

    def obj(self, query_id):
        identities = {
            "mgmt-namespace": ("v1", "Namespace", None, "disposable-ok141"),
            "infra-namespace": ("v1", "Namespace", None, "disposable-ok141"),
            "golden-image-cloner-role": ("rbac.authorization.k8s.io/v1", "Role", "ok-images", "disposable-ok141-talos-golden-image-cloner"),
            "golden-image-cloner-binding": ("rbac.authorization.k8s.io/v1", "RoleBinding", "ok-images", "disposable-ok141-talos-golden-image-cloner"),
            "misrouted-load-balancer": ("v1", "Service", "disposable-ok141", "disposable-ok141-lb"),
        }
        api, kind, namespace, name = identities.get(
            query_id, ("test.openkubes.io/v1", "TestObject", "disposable-ok141", query_id)
        )
        return {
            "apiVersion": api,
            "kind": kind,
            "name": name,
            "namespace": namespace,
            "uid": f"uid-{query_id}",
            "resourceVersion": "100",
            "generation": 1,
            "deletionTimestamp": None,
            "finalizers": [],
            "ownerReferences": [],
            "intentRevision": None if query_id == "misrouted-load-balancer" else MAT.BASE.FAILED_INTENT,
        }

    def evidence(self):
        def present(query_id):
            return {"id": query_id, "outcome": "PRESENT", "objects": [self.obj(query_id)]}

        def empty(query_id, outcome):
            return {"id": query_id, "outcome": outcome, "objects": []}

        candidate = OBS.verify_candidate(SNAPSHOT)
        return {
            "candidateDigest": MAT.BASE.sha(SNAPSHOT),
            "attemptID": candidate["spec"]["attempt"]["id"],
            "grantID": "test-attempt-grant",
            "startedAt": "2026-08-14T08:29:59Z",
            "completedAt": "2026-08-14T08:30:00Z",
            "credentialBytesEmitted": False,
            "credentialUseAuthorized": True,
            "secretReadsPerformed": False,
            "mutationPerformed": False,
            "planes": {
                "ok-mgmt": [present(item) for item in MAT.BASE.MGMT_PRESENT]
                + [empty(item, "ABSENT") for item in MAT.BASE.MGMT_ABSENT]
                + [empty(item, "API_NOT_SERVED") for item in MAT.BASE.MGMT_API_NOT_SERVED],
                "ok-infra": [present(item) for item in MAT.BASE.INFRA_PRESENT]
                + [empty(item, "ABSENT") for item in MAT.BASE.INFRA_ABSENT],
            },
        }

    def test_attempt_is_reproducible_and_not_authorized(self):
        candidate = OBS.verify_candidate(SNAPSHOT)
        self.assertEqual(candidate["spec"]["attempt"]["sequence"], 4)
        self.assertEqual(candidate["spec"]["runtimeBinding"]["freshnessMaximumMinutes"], 10)
        self.assertFalse(any(candidate["spec"]["authorization"].values()))
        self.assertEqual(MAT.BASE.sha(SNAPSHOT), "sha256:243e7eb9b6633e13c7436be2b317f2621c6cc7b4ef44d8cb870aba5d59810b5e")

    def test_query_history_output_or_authority_tampering_fails_closed(self):
        for mutation in ("query", "history", "output", "authority"):
            changed = copy.deepcopy(OBS.V1.read(SNAPSHOT))
            if mutation == "query":
                changed["spec"]["planes"]["ok-mgmt"]["queries"][0]["rawURI"] += "-wrong"
            elif mutation == "history":
                changed["spec"]["attempt"]["predecessor"]["disposition"] = "unknown"
            elif mutation == "output":
                changed["spec"]["evidence"]["outputPath"] = "/private/tmp/reused.json"
            else:
                changed["spec"]["authorization"]["cleanupAuthorized"] = True
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(OBS.SnapshotError):
                    OBS.verify_candidate(self.write_yaml(temporary, "candidate.yaml", changed))

    def test_current_bounded_grant_is_accepted_and_retry_is_rejected(self):
        grant = OBS.V1.read(HERE / "recovery-snapshot-grant-v3.template.yaml")
        grant["spec"].update(
            {
                "state": "GRANTED",
                "candidateDigest": MAT.BASE.sha(SNAPSHOT),
                "grantID": "test-attempt-grant",
                "notBefore": "2026-08-14T08:20:00Z",
                "notAfter": "2026-08-14T08:40:00Z",
                "maximumRuns": 1,
                "outputPath": OBS.verify_candidate(SNAPSHOT)["spec"]["evidence"]["outputPath"],
                "readOnlyAuthorized": True,
                "credentialUseAuthorized": True,
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write_yaml(temporary, "grant.yaml", grant)
            OBS.verify_grant(SNAPSHOT, path, dt.datetime(2026, 8, 14, 8, 30, tzinfo=dt.timezone.utc))
            grant["spec"]["retryAuthorized"] = True
            bad = self.write_yaml(temporary, "bad.yaml", grant)
            with self.assertRaises(OBS.SnapshotError):
                OBS.verify_grant(SNAPSHOT, bad, dt.datetime(2026, 8, 14, 8, 30, tzinfo=dt.timezone.utc))

    def test_attempt_evidence_materializes_binding_for_exact_cleanup_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = self.write_evidence(temporary, self.evidence())
            binding = MAT.materialize(evidence, SNAPSHOT)
            configured = OBS.verify_candidate(SNAPSHOT)["spec"]["runtimeBinding"]
            self.assertEqual(binding["metadata"]["name"], configured["name"])
            self.assertEqual(binding["spec"]["bindingVersion"], CLEAN.BINDING_VERSION)
            binding_path = Path(temporary) / "binding.yaml"
            binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
            candidate = CLEAN.validate_candidate(CLEANUP)
            CLEAN.validate_binding(
                candidate, binding_path, CLEAN.BASE.timestamp("2026-08-14T08:35:00Z")
            )

    def test_wrong_attempt_or_candidate_binding_fails_closed(self):
        for mutation in ("attempt", "candidate"):
            with tempfile.TemporaryDirectory() as temporary:
                evidence = self.write_evidence(temporary, self.evidence())
                binding = MAT.materialize(evidence, SNAPSHOT)
                if mutation == "attempt":
                    binding["spec"]["attemptID"] = "r0-v99-20990101-01"
                else:
                    binding["spec"]["sourceObservationCandidateDigest"] = "sha256:" + "0" * 64
                binding_path = Path(temporary) / "binding.yaml"
                binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
                candidate = CLEAN.validate_candidate(CLEANUP)
                with self.assertRaises(CLEAN.CleanupError):
                    CLEAN.validate_binding(
                        candidate, binding_path, CLEAN.BASE.timestamp("2026-08-14T08:35:00Z")
                    )


if __name__ == "__main__":
    unittest.main()
