import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = load("materialize_recovery_binding_v1_test", HERE / "materialize_recovery_binding_v1.py")
CLEANUP = load("bounded_recovery_cleanup_v1_materializer_test", HERE / "bounded_recovery_cleanup_v1.py")


class RecoveryBindingMaterializerTests(unittest.TestCase):
    def obj(self, query_id):
        identities = {
            "mgmt-namespace": ("v1", "Namespace", None, "disposable-ok141"),
            "infra-namespace": ("v1", "Namespace", None, "disposable-ok141"),
            "golden-image-cloner-role": ("rbac.authorization.k8s.io/v1", "Role", "ok-images", "disposable-ok141-talos-golden-image-cloner"),
            "golden-image-cloner-binding": ("rbac.authorization.k8s.io/v1", "RoleBinding", "ok-images", "disposable-ok141-talos-golden-image-cloner"),
            "misrouted-load-balancer": ("v1", "Service", "disposable-ok141", "disposable-ok141-lb"),
        }
        api, kind, namespace, name = identities.get(query_id, ("test.openkubes.io/v1", "TestObject", "disposable-ok141", query_id))
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
            "intentRevision": None if query_id == "misrouted-load-balancer" else MODULE.FAILED_INTENT,
        }

    def evidence(self):
        def present(query_id):
            return {"id": query_id, "outcome": "PRESENT", "objects": [self.obj(query_id)]}
        def empty(query_id, outcome):
            return {"id": query_id, "outcome": outcome, "objects": []}
        return {
            "candidateDigest": MODULE.OBSERVATION_CANDIDATE_DIGEST,
            "grantID": "test-grant",
            "startedAt": "2026-08-14T07:59:59Z",
            "completedAt": "2026-08-14T08:00:00Z",
            "credentialBytesEmitted": False,
            "credentialUseAuthorized": True,
            "secretReadsPerformed": False,
            "mutationPerformed": False,
            "planes": {
                "ok-mgmt": [present(item) for item in MODULE.MGMT_PRESENT]
                + [empty(item, "ABSENT") for item in MODULE.MGMT_ABSENT]
                + [empty(item, "API_NOT_SERVED") for item in MODULE.MGMT_API_NOT_SERVED],
                "ok-infra": [present(item) for item in MODULE.INFRA_PRESENT]
                + [empty(item, "ABSENT") for item in MODULE.INFRA_ABSENT],
            },
        }

    def write(self, directory, value):
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(value, sort_keys=True))
        path.chmod(0o600)
        return path

    def test_valid_snapshot_materializes_private_fresh_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write(temp, self.evidence())
            binding = MODULE.materialize(path)
            spec = binding["spec"]
            self.assertEqual(spec["expiresAt"], "2026-08-14T08:10:00+00:00")
            self.assertFalse(spec["credentialsIncluded"])
            self.assertFalse(spec["publicUIDPublicationAllowed"])
            candidate = CLEANUP.validate_candidate(HERE / "recovery-cleanup-candidate-v1.yaml")
            binding_path = Path(temp) / "binding.yaml"
            import yaml
            binding_path.write_text(yaml.safe_dump(binding, sort_keys=False))
            CLEANUP.validate_binding(candidate, binding_path, CLEANUP.timestamp("2026-08-14T08:05:00Z"))

    def test_wrong_outcome_or_query_set_fails_closed(self):
        for mutation in ("outcome", "missing"):
            value = self.evidence()
            if mutation == "outcome":
                value["planes"]["ok-infra"][-1]["outcome"] = "PRESENT"
            else:
                value["planes"]["ok-mgmt"].pop()
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MODULE.BindingError):
                    MODULE.validate_snapshot(self.write(temp, value))

    def test_wrong_intent_or_deleting_target_fails_closed(self):
        for mutation in ("intent", "deleting"):
            value = self.evidence()
            target = value["planes"]["ok-infra"][0]["objects"][0]
            if mutation == "intent":
                target["intentRevision"] = "sha256:" + "0" * 64
            else:
                target["deletionTimestamp"] = "2026-08-14T08:00:01Z"
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MODULE.BindingError):
                    MODULE.validate_snapshot(self.write(temp, value))

    def test_security_boundary_flag_fails_closed(self):
        for claim in ("credentialBytesEmitted", "secretReadsPerformed", "mutationPerformed"):
            value = self.evidence()
            value[claim] = True
            with tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MODULE.BindingError):
                    MODULE.validate_snapshot(self.write(temp, value))


if __name__ == "__main__":
    unittest.main()
