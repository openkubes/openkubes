import copy
import datetime as dt
import importlib.util
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


PREPARE = load("prepare_recovery_r3_binding_test", HERE / "prepare_recovery_r3_binding_v1.py")
CLEAN = load("bounded_recovery_r3_cleanup_test", HERE / "bounded_recovery_r3_cleanup_v1.py")
TEMPLATE = HERE / "recovery-r3-binding-candidate-v1.template.yaml"
CANDIDATE = HERE / "recovery-r3-cleanup-candidate-v1.yaml"


class RecoveryR3Tests(unittest.TestCase):
    def write(self, directory, name, value, mode=None):
        path = Path(directory) / name
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        if mode is not None:
            path.chmod(mode)
        return path

    def preflight_candidate(self):
        value = PREPARE.V1.read(TEMPLATE)
        value["metadata"]["name"] = "ok141-r3-test"
        value["spec"]["state"] = "READY-FOR-EXPLICIT-READ-ONLY-GRANT"
        value["spec"]["predecessor"].update(
            {
                "r2CandidateDigest": "sha256:" + "1" * 64,
                "r2EvidenceDigest": "sha256:" + "2" * 64,
                "r2State": "PASS-R2-CLEAN",
            }
        )
        value["spec"]["attempt"]["id"] = "r3-v1-20260814-01"
        value["spec"]["evidence"].update(
            {
                "outputPath": "/private/tmp/ok141-go1-l-recovery-r3-v1-20260814-01-preflight-evidence.json",
                "bindingOutputPath": "/private/tmp/ok141-go1-l-recovery-r3-v1-20260814-01-runtime-binding.yaml",
            }
        )
        return value

    def retained(self, query):
        api, kind, namespace, name = query["identity"].split("|")
        return {
            "apiVersion": api,
            "kind": kind,
            "name": name,
            "namespace": None if namespace == "_" else namespace,
            "uid": f"uid-{query['id']}",
            "resourceVersion": "100",
            "generation": 1,
            "deletionTimestamp": None,
            "finalizers": [],
            "ownerReferences": [],
            "intentRevision": PREPARE.FAILED_INTENT,
        }

    def binding(self):
        return {
            "apiVersion": "recovery.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryR3RuntimeBinding",
            "metadata": {"name": "ok141-r3-binding", "ticket": "OK-141"},
            "spec": {
                "state": "READY-FOR-EXPLICIT-R3-DELETE-GRANT",
                "protocolDigest": PREPARE.PROTOCOL_DIGEST,
                "attemptID": "r3-v1-20260814-01",
                "observedAt": "2026-08-14T09:00:00Z",
                "expiresAt": "2026-08-14T09:10:00Z",
                "sourceCandidateDigest": "sha256:" + "1" * 64,
                "sourceEvidenceDigest": "sha256:" + "2" * 64,
                "sourceR2EvidenceDigest": "sha256:" + "3" * 64,
                "objects": {
                    query["id"]: {
                        "identity": query["identity"],
                        "uid": f"uid-{query['id']}",
                        "resourceVersion": "100",
                        "deletionTimestamp": None,
                        "finalizers": [],
                        "ownerReferences": [],
                        "intentRevision": PREPARE.FAILED_INTENT,
                    }
                    for query in PREPARE.TARGETS
                },
                "credentialsIncluded": False,
                "publicUIDPublicationAllowed": False,
                "executable": False,
            },
        }

    def grant(self, binding_path):
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryR3CleanupGrant",
            "metadata": {"name": "test", "ticket": "OK-141"},
            "spec": {
                "state": "GRANTED",
                "candidateDigest": CLEAN.BASE.sha(CANDIDATE),
                "privateRuntimeBindingDigest": CLEAN.BASE.sha(binding_path),
                "grantID": "test-r3",
                "notBefore": "2026-08-14T09:00:00Z",
                "notAfter": "2026-08-14T09:10:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "outputPath": "/private/tmp/ok141-go1-l-recovery-r3-cleanup-evidence.json",
                "readOnlyPreconditionAuthorized": True,
                "credentialUseAuthorized": True,
                "mutationAuthorized": True,
                "destructiveCleanupAuthorized": True,
                "uidPreconditionAuthorized": True,
                "retryAuthorized": False,
                "forceDeleteAuthorized": False,
                "finalizerRemovalAuthorized": False,
                "secretReadAuthorized": False,
                "recreateAuthorized": False,
                "go1LAuthorized": False,
                "go1Authorized": False,
                "failureInjectionAuthorized": False,
            },
        }

    def test_preflight_candidate_is_exact_and_not_authorized(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = self.write(temporary, "candidate.yaml", self.preflight_candidate())
            candidate = PREPARE.verify_candidate(path)
            self.assertEqual(candidate["spec"]["queries"], PREPARE.TARGETS)
            self.assertFalse(any(candidate["spec"]["authorization"].values()))

    def test_preflight_tampering_and_unsafe_object_state_fail_closed(self):
        changed = self.preflight_candidate()
        changed["spec"]["queries"].reverse()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(PREPARE.R3Error):
                PREPARE.verify_candidate(self.write(temporary, "candidate.yaml", changed))
        query = PREPARE.TARGETS[0]
        result = {"id": query["id"], "outcome": "PRESENT", "objects": [self.retained(query)]}
        PREPARE.validate_result(query, result)
        result["objects"][0]["finalizers"] = ["unsafe"]
        with self.assertRaises(PREPARE.R3Error):
            PREPARE.validate_result(query, result)

    def test_cleanup_candidate_is_exact_ordered_and_not_authorized(self):
        candidate = CLEAN.validate_candidate(CANDIDATE)
        self.assertEqual([item["key"] for item in candidate["spec"]["targets"]], [
            "golden-image-cloner-binding", "golden-image-cloner-role", "infra-namespace"
        ])
        self.assertEqual(CLEAN.BASE.sha(CANDIDATE), "sha256:71ef9c406a772bae02bdb0706e09cc49a772afb3d29a5ee87c11ae93144f4664")

    def test_fresh_binding_and_single_run_grant_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding_path = self.write(temporary, "binding.yaml", self.binding(), 0o600)
            binding = CLEAN.validate_binding(binding_path, dt.datetime(2026, 8, 14, 9, 5, tzinfo=dt.timezone.utc))
            self.assertEqual([item.identity for item in CLEAN.targets(binding)], [item["identity"] for item in CLEAN.TARGETS])
            grant_path = self.write(temporary, "grant.yaml", self.grant(binding_path))
            CLEAN.validate_grant(
                CANDIDATE, binding_path, grant_path,
                dt.datetime(2026, 8, 14, 9, 5, tzinfo=dt.timezone.utc),
            )

    def test_stale_or_wrong_binding_and_retry_grant_fail_closed(self):
        for mutation in ("stale", "identity"):
            value = self.binding()
            if mutation == "stale":
                value["spec"]["expiresAt"] = "2026-08-14T09:11:00Z"
            else:
                value["spec"]["objects"]["infra-namespace"]["identity"] += "-wrong"
            with tempfile.TemporaryDirectory() as temporary:
                path = self.write(temporary, "binding.yaml", value, 0o600)
                with self.assertRaises(CLEAN.R3CleanupError):
                    CLEAN.validate_binding(path, dt.datetime(2026, 8, 14, 9, 5, tzinfo=dt.timezone.utc))
        with tempfile.TemporaryDirectory() as temporary:
            binding_path = self.write(temporary, "binding.yaml", self.binding(), 0o600)
            grant = self.grant(binding_path)
            grant["spec"]["retryAuthorized"] = True
            grant_path = self.write(temporary, "grant.yaml", grant)
            with self.assertRaises(CLEAN.R3CleanupError):
                CLEAN.validate_grant(
                    CANDIDATE, binding_path, grant_path,
                    dt.datetime(2026, 8, 14, 9, 5, tzinfo=dt.timezone.utc),
                )


if __name__ == "__main__":
    unittest.main()
