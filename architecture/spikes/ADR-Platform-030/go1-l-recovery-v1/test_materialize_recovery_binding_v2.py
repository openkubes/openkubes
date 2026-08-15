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


MODULE = load("materialize_recovery_binding_v2_test", HERE / "materialize_recovery_binding_v2.py")
CLEANUP = load("bounded_recovery_cleanup_v2_materializer_test", HERE / "bounded_recovery_cleanup_v2.py")
CANDIDATE = HERE / "recovery-cleanup-candidate-v1-r0-v3.yaml"


class RecoveryBindingMaterializerV2Tests(unittest.TestCase):
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
            "intentRevision": None if query_id == "misrouted-load-balancer" else MODULE.BASE.FAILED_INTENT,
        }

    def evidence(self):
        def present(query_id):
            return {"id": query_id, "outcome": "PRESENT", "objects": [self.obj(query_id)]}

        def empty(query_id, outcome):
            return {"id": query_id, "outcome": outcome, "objects": []}

        return {
            "candidateDigest": MODULE.OBSERVATION_CANDIDATE_DIGEST,
            "grantID": "test-r0-v3-grant",
            "startedAt": "2026-08-14T07:59:59Z",
            "completedAt": "2026-08-14T08:00:00Z",
            "credentialBytesEmitted": False,
            "credentialUseAuthorized": True,
            "secretReadsPerformed": False,
            "mutationPerformed": False,
            "planes": {
                "ok-mgmt": [present(item) for item in MODULE.BASE.MGMT_PRESENT]
                + [empty(item, "ABSENT") for item in MODULE.BASE.MGMT_ABSENT]
                + [empty(item, "API_NOT_SERVED") for item in MODULE.BASE.MGMT_API_NOT_SERVED],
                "ok-infra": [present(item) for item in MODULE.BASE.INFRA_PRESENT]
                + [empty(item, "ABSENT") for item in MODULE.BASE.INFRA_ABSENT],
            },
        }

    def write(self, directory, value):
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(value, sort_keys=True))
        path.chmod(0o600)
        return path

    def test_v3_snapshot_materializes_v2_binding_accepted_by_v2_executor(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = self.write(temporary, self.evidence())
            binding = MODULE.materialize(evidence_path)
            self.assertEqual(binding["metadata"]["name"], CLEANUP.BINDING_NAME)
            self.assertEqual(binding["spec"]["bindingVersion"], CLEANUP.BINDING_VERSION)
            self.assertEqual(
                binding["spec"]["sourceObservationCandidateDigest"], MODULE.OBSERVATION_CANDIDATE_DIGEST
            )
            binding_path = Path(temporary) / "binding.yaml"
            binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
            candidate = CLEANUP.validate_candidate(CANDIDATE)
            CLEANUP.validate_binding(
                candidate, binding_path, CLEANUP.BASE.timestamp("2026-08-14T08:05:00Z")
            )

    def test_legacy_snapshot_or_binding_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            legacy = self.evidence()
            legacy["candidateDigest"] = "sha256:4cc18693b948844a0516492395e7943cd1f1925d66b35f25d35977c989bac71f"
            with self.assertRaises(MODULE.BindingError):
                MODULE.validate_snapshot(self.write(temporary, legacy))

        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = self.write(temporary, self.evidence())
            binding = MODULE.materialize(evidence_path)
            binding["spec"]["sourceObservationCandidateDigest"] = "sha256:" + "0" * 64
            binding_path = Path(temporary) / "binding.yaml"
            binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
            candidate = CLEANUP.validate_candidate(CANDIDATE)
            with self.assertRaises(CLEANUP.CleanupError):
                CLEANUP.validate_binding(
                    candidate, binding_path, CLEANUP.BASE.timestamp("2026-08-14T08:05:00Z")
                )

    def test_security_boundary_and_query_outcome_still_fail_closed(self):
        for mutation in ("security", "outcome"):
            value = self.evidence()
            if mutation == "security":
                value["mutationPerformed"] = True
            else:
                value["planes"]["ok-infra"][-1]["outcome"] = "PRESENT"
            with tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(MODULE.BindingError):
                    MODULE.validate_snapshot(self.write(temporary, value))


if __name__ == "__main__":
    unittest.main()
