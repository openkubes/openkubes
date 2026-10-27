from __future__ import annotations

import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_go1_l_runtime_package_v1_test", HERE / "bounded_go1_l_runtime_package_v1.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RuntimePackageTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)
        self.expires = self.now + dt.timedelta(minutes=15)
        self.run_id = "ok141-go1-l-test-run-001"

    def preflight(self, directory: Path) -> Path:
        value = {"spec": {"candidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2", "result": "PASS-FRESH-BASELINE-AND-PREREQUISITES", "mutationPerformed": False, "secretBodiesRetained": False, "freshUntil": "2026-08-14T12:05:00Z", "credentialIdentityDigests": {"ok-infra": "sha256:0cab42fab537845afb82ef510169bf9402e314e0fcb3ebce972499e0a1cd8f13", "ok-mgmt": "sha256:32a164332776f37129e46415af79945745134fefe80c5237d43fe13fa0511ffe"}}}
        path = directory / "preflight.json"
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def grant(self, directory: Path, stage: str, preflight: Path, lifecycle: Path | None = None, overbroad: bool = False) -> Path:
        value = {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1LStageGrant", "spec": {"decision": "GO", "authority": "github:arashkaffamanesh", "stage": stage, "singleRun": True, "candidateDigest": MODULE.sha(MODULE.CANDIDATE), "executorDigest": "sha256:0f9693df9b89bc96278f69134517fb2777a60373a61fadc40612cdaacdc2115c", "protocolDigest": "sha256:e45e5f6b8254e666226aa874810bf2ca51f76f2411e0316adb52a7ce51254885", "preflightCandidateDigest": "sha256:ef4b09a8835f187605a0120bdd19616d6d078b9ed19a3796a47b9cbbfc7a4fb2", "preflightEvidenceDigest": MODULE.sha(preflight), "credentialUseGranted": True, "go1LGranted": True, "g1Granted": stage == "G1", "g3Granted": stage == "G3", "go1Granted": False, "retryGranted": overbroad, "rollbackOrCleanupGranted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False, "grantID": f"ok141-runtime-test-{stage.lower()}", "runID": self.run_id, "issuedAt": MODULE.iso(self.now - dt.timedelta(minutes=1)), "expiresAt": MODULE.iso(self.expires)}}
        if lifecycle is not None:
            value["spec"]["lifecycleEvidenceDigest"] = MODULE.sha(lifecycle)
        path = directory / f"outer-{stage.lower()}.yaml"
        path.write_text(yaml.safe_dump(value, sort_keys=True))
        return path

    def test_candidate_is_inert_and_exact(self):
        candidate, _ = MODULE.validate_candidate()
        plan = MODULE.plan()
        self.assertEqual((HERE / "go1-l-runtime-package-candidate-v1.sha256").read_text().strip(), MODULE.sha(MODULE.CANDIDATE))
        self.assertEqual(candidate["spec"]["state"], "OFFLINE-PROVEN-BLOCKED-NO-GO")
        self.assertEqual(plan["receiptCount"], 6)
        self.assertFalse(plan["mutationAuthorized"])
        self.assertFalse(plan["clusterContacted"])

    def test_g1_derives_exact_chain_and_five_receipts(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.preflight(directory)
            outer = self.grant(directory, "G1", preflight)
            run_dir = directory / self.run_id

            def runtime_directory(candidate, run_id, create):
                self.assertEqual(run_id, self.run_id)
                run_dir.mkdir(mode=0o700, exist_ok=False)
                return run_dir

            def static_result(_, operation, *__args, **__kwargs):
                counts = {"provider-prerequisites": 3, "management-namespace": 1, "capi-lifecycle": 7}
                return {"operation": operation, "targetPlane": "ok-infra" if operation == "provider-prerequisites" else "ok-mgmt", "objectCount": counts[operation], "semanticDigest": "sha256:" + "1" * 64, "transportExitCode": 0}

            provider_result = {"operation": "provider-access-secret", "targetPlane": "ok-mgmt", "secretIdentity": "v1|Secret|disposable-ok141|external-infra-kubeconfig-disposable-ok141", "transportExitCode": 0}
            with mock.patch.object(MODULE, "run_directory", side_effect=runtime_directory), mock.patch.object(MODULE.EXEC, "execute_static", side_effect=static_result), mock.patch.object(MODULE.EXEC, "execute_provider", return_value=provider_result):
                result = MODULE.execute_g1(MODULE.CANDIDATE, outer, preflight, self.now, clock=lambda: self.now)

            self.assertEqual(result["mutationCount"], 12)
            self.assertEqual(len(list(run_dir.glob("receipt-*.json"))), 5)
            self.assertEqual(len(list(run_dir.glob("grant-*.json"))), 4)
            capi = json.loads((run_dir / "grant-capi-lifecycle.json").read_text())["spec"]
            expected = [MODULE.sha(run_dir / "evidence-management-namespace.json"), MODULE.sha(run_dir / "evidence-provider-access-secret.json")]
            self.assertEqual(capi["predecessorEvidenceDigests"], expected)
            self.assertFalse(capi["retryGranted"])

    def test_g3_requires_exact_lifecycle_evidence_and_adds_sixth_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.preflight(directory)
            lifecycle = directory / "lifecycle.json"
            lifecycle.write_text(json.dumps({"result": "CONTROL-PLANE-API-READY"}))
            outer = self.grant(directory, "G3", preflight, lifecycle)
            run_dir = directory / self.run_id
            run_dir.mkdir(mode=0o700)

            def runtime_directory(candidate, run_id, create):
                self.assertFalse(create)
                return run_dir

            static = {"operation": "helmchartproxy", "targetPlane": "ok-mgmt", "objectCount": 1, "semanticDigest": "sha256:" + "2" * 64, "transportExitCode": 0}
            with mock.patch.object(MODULE, "run_directory", side_effect=runtime_directory), mock.patch.object(MODULE.EXEC, "execute_static", return_value=static):
                result = MODULE.execute_g3(MODULE.CANDIDATE, outer, preflight, lifecycle, self.now)
            self.assertEqual(result["operation"], "helmchartproxy")
            inner = json.loads((run_dir / "grant-helmchartproxy.json").read_text())["spec"]
            self.assertEqual(inner["predecessorEvidenceDigests"], [MODULE.sha(lifecycle)])

    def test_overbroad_outer_grant_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            preflight = self.preflight(directory)
            grant = self.grant(directory, "G1", preflight, overbroad=True)
            with self.assertRaises(MODULE.RuntimePackageError):
                MODULE.validate_outer_grant(MODULE.CANDIDATE, grant, "G1", self.now)


if __name__ == "__main__":
    unittest.main()
