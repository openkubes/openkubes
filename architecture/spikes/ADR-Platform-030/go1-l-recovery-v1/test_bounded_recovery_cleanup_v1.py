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
SPEC = importlib.util.spec_from_file_location("bounded_recovery_cleanup_v1_test", HERE / "bounded_recovery_cleanup_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecoveryCleanupTests(unittest.TestCase):
    def setUp(self):
        self.candidate_path = HERE / "recovery-cleanup-candidate-v1.yaml"
        self.candidate = MODULE.validate_candidate(self.candidate_path)
        self.now = dt.datetime(2026, 8, 14, 8, 5, tzinfo=dt.timezone.utc)

    def binding(self):
        target = lambda identity, uid: {
            "identity": identity,
            "uid": uid,
            "resourceVersion": "100",
            "deletionTimestamp": None,
            "finalizers": [],
            "ownerReferences": [],
        }
        return {
            "apiVersion": "recovery.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryRuntimeBinding",
            "spec": {
                "state": "READY-FOR-EXPLICIT-UID-PRECONDITIONED-CLEANUP-GRANT",
                "protocolDigest": self.candidate["spec"]["sourceProtocol"]["digest"],
                "observedAt": "2026-08-14T08:00:00Z",
                "expiresAt": "2026-08-14T08:10:00Z",
                "sourceEvidenceDigests": ["sha256:" + "1" * 64],
                "objects": {
                    "okMgmt": {
                        "namespace": target("v1|Namespace|_|disposable-ok141", "uid-mgmt"),
                    },
                    "okInfra": {
                        "roleBinding": target("rbac.authorization.k8s.io/v1|RoleBinding|ok-images|disposable-ok141-talos-golden-image-cloner", "uid-rb"),
                        "role": target("rbac.authorization.k8s.io/v1|Role|ok-images|disposable-ok141-talos-golden-image-cloner", "uid-role"),
                        "namespace": target("v1|Namespace|_|disposable-ok141", "uid-infra"),
                    },
                },
                "credentialsIncluded": False,
                "executable": False,
            },
        }

    def write_yaml(self, directory: Path, name: str, value):
        path = directory / name
        path.write_text(yaml.safe_dump(value, sort_keys=True))
        return path

    def grant(self, binding_path: Path, stage="R1"):
        return {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1LRecoveryCleanupGrant",
            "spec": {
                "state": "GRANTED",
                "candidateDigest": MODULE.sha(self.candidate_path),
                "protocolDigest": self.candidate["spec"]["sourceProtocol"]["digest"],
                "privateRuntimeBindingDigest": MODULE.sha(binding_path),
                "authorizedStage": stage,
                "grantID": "test-only",
                "notBefore": "2026-08-14T08:00:00Z",
                "notAfter": "2026-08-14T08:10:00Z",
                "maximumRuns": 1,
                "consumed": False,
                "outputPath": f"/private/tmp/ok141-go1-l-recovery-{stage.lower()}-cleanup-evidence.json",
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

    def test_candidate_is_offline_and_has_two_separate_stages(self):
        self.assertEqual([item["id"] for item in self.candidate["spec"]["stages"]], ["R1", "R3"])
        self.assertEqual(self.candidate["spec"]["authorization"]["decision"], "NO-GO")

    def test_candidate_authority_or_transport_tampering_fails_closed(self):
        for path, value in [
            (("authorization", "mutationAuthorized"), True),
            (("transport", "forceAllowed"), True),
            (("transport", "uidPreconditionRequired"), False),
        ]:
            changed = copy.deepcopy(self.candidate)
            changed["spec"][path[0]][path[1]] = value
            with tempfile.TemporaryDirectory() as temp:
                candidate_path = self.write_yaml(Path(temp), "candidate.yaml", changed)
                changed["spec"]["sourceProtocol"]["path"] = str(HERE / "go1-l-recovery-protocol-v1.yaml")
                changed["spec"]["tool"]["path"] = str(HERE / "bounded_recovery_cleanup_v1.py")
                changed["spec"]["runtimeBindingMaterializer"]["path"] = str(HERE / "materialize_recovery_binding_v1.py")
                candidate_path.write_text(yaml.safe_dump(changed, sort_keys=True))
                with self.assertRaises(MODULE.CleanupError):
                    MODULE.validate_candidate(candidate_path)

    def test_binding_freshness_uid_and_ownership_are_required(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for mutation in ("stale", "uid", "finalizer"):
                value = self.binding()
                if mutation == "stale":
                    value["spec"]["expiresAt"] = "2026-08-14T08:04:00Z"
                elif mutation == "uid":
                    value["spec"]["objects"]["okMgmt"]["namespace"]["uid"] = None
                else:
                    value["spec"]["objects"]["okInfra"]["role"]["finalizers"] = ["unexpected"]
                path = self.write_yaml(directory, f"{mutation}.yaml", value)
                with self.assertRaises(MODULE.CleanupError):
                    MODULE.validate_binding(self.candidate, path, self.now)

    def test_grant_is_single_stage_current_and_excludes_force_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            binding_path = self.write_yaml(directory, "binding.yaml", self.binding())
            grant = self.grant(binding_path)
            grant_path = self.write_yaml(directory, "grant.yaml", grant)
            MODULE.validate_binding(self.candidate, binding_path, self.now)
            MODULE.validate_grant(self.candidate_path, self.candidate, binding_path, grant_path, "R1", self.now)
            for claim in ("retryAuthorized", "forceDeleteAuthorized", "finalizerRemovalAuthorized"):
                changed = copy.deepcopy(grant)
                changed["spec"][claim] = True
                changed_path = self.write_yaml(directory, f"{claim}.yaml", changed)
                with self.assertRaises(MODULE.CleanupError):
                    MODULE.validate_grant(self.candidate_path, self.candidate, binding_path, changed_path, "R1", self.now)

    def test_r1_and_r3_plans_are_exact_and_ordered(self):
        with tempfile.TemporaryDirectory() as temp:
            path = self.write_yaml(Path(temp), "binding.yaml", self.binding())
            binding = MODULE.validate_binding(self.candidate, path, self.now)
            plane, r1 = MODULE.stage_targets(self.candidate, binding, "R1")
            self.assertEqual(plane, "ok-mgmt")
            self.assertEqual([item.key for item in r1], ["okMgmt.namespace"])
            plane, r3 = MODULE.stage_targets(self.candidate, binding, "R3")
            self.assertEqual(plane, "ok-infra")
            self.assertEqual([item.key for item in r3], ["okInfra.roleBinding", "okInfra.role", "okInfra.namespace"])

    def test_live_uid_or_resource_version_mismatch_stops_before_delete(self):
        target = MODULE.Target("okMgmt.namespace", "v1|Namespace|_|disposable-ok141", "/api/v1/namespaces/disposable-ok141", "expected", "100")
        for metadata in ({"uid": "wrong", "resourceVersion": "100"}, {"uid": "expected", "resourceVersion": "101"}):
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                return Completed(stdout=json.dumps({"metadata": metadata}))
            with self.assertRaises(MODULE.CleanupError):
                MODULE.run_get(MODULE.TOOL, Path("/private/tmp/test"), target, runner)
            self.assertEqual(len(calls), 1)

    def test_delete_uses_only_raw_uri_uid_precondition_and_foreground(self):
        target = MODULE.Target("okMgmt.namespace", "v1|Namespace|_|disposable-ok141", "/api/v1/namespaces/disposable-ok141", "expected-uid", "100")
        calls = []
        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return Completed()
        MODULE.run_delete(MODULE.TOOL, Path("/private/tmp/test"), target, runner)
        command, kwargs = calls[0]
        self.assertEqual(command[-3:], ["--raw=/api/v1/namespaces/disposable-ok141", "--filename=-", "--wait=false"])
        payload = json.loads(kwargs["input"])
        self.assertEqual(payload["preconditions"], {"resourceVersion": "100", "uid": "expected-uid"})
        self.assertEqual(payload["propagationPolicy"], "Foreground")
        self.assertNotIn("gracePeriodSeconds", payload)

    def test_partial_r3_state_is_persisted_before_fail_closed_stop(self):
        targets = [
            MODULE.Target("first", "identity-first", "/api/v1/namespaces/first", "uid-first", "100"),
            MODULE.Target("second", "identity-second", "/api/v1/namespaces/second", "uid-second", "200"),
        ]
        calls = []
        def runner(command, **kwargs):
            calls.append(command)
            if "get" in command:
                target = targets[0] if "first" in command[-1] else targets[1]
                return Completed(stdout=json.dumps({"metadata": {"uid": target.uid, "resourceVersion": target.resource_version}}))
            if "second" in command[-3]:
                return Completed(returncode=1, stderr="redacted failure")
            return Completed()
        with tempfile.TemporaryDirectory() as temp:
            evidence_path = Path(temp) / "evidence.json"
            evidence = {
                "state": "STARTED-NO-DELETE-ATTEMPTED",
                "submittedIdentities": [],
                "currentTarget": None,
                "deleteAttempted": False,
            }
            with self.assertRaises(MODULE.CleanupError):
                MODULE.perform_targets(evidence_path, evidence, targets, MODULE.TOOL, Path("/private/tmp/test"), runner)
            retained = json.loads(evidence_path.read_text())
            self.assertEqual(retained["state"], "STOPPED-PRESERVE-NO-RETRY")
            self.assertEqual(retained["submittedIdentities"], ["identity-first"])
            self.assertEqual(retained["currentTarget"], "identity-second")
            self.assertTrue(retained["deleteAttempted"])
            self.assertEqual(evidence_path.stat().st_mode & 0o777, 0o600)

    def test_grant_template_carries_no_authority(self):
        template = MODULE.read(HERE / "recovery-cleanup-grant-v1.template.yaml")["spec"]
        self.assertEqual(template["state"], "TEMPLATE-NOT-GRANTED")
        self.assertEqual(template["maximumRuns"], 0)
        self.assertFalse(any(value for key, value in template.items() if key.endswith("Authorized")))


if __name__ == "__main__":
    unittest.main()
