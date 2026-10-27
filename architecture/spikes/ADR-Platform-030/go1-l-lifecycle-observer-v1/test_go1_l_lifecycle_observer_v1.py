import copy
import datetime as dt
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_lifecycle_observer_test", HERE / "bounded_go1_l_lifecycle_observer_v1.py")
OBS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OBS
assert SPEC.loader is not None
SPEC.loader.exec_module(OBS)


def obj(api, kind, name, generation=1, observed=1, conditions=None):
    return {
        "apiVersion": api,
        "kind": kind,
        "metadata": {
            "name": name,
            "namespace": "disposable-ok141",
            "uid": f"uid-{name}",
            "generation": generation,
            "annotations": {"openkubes.io/intent-revision": "sha256:166504ae61fd558d391daedde50986cbc7a28f5f4e9d57f4acbd0433b448aa0f"},
        },
        "status": {"observedGeneration": observed, "conditions": conditions or []},
    }


class LifecycleObserverTests(unittest.TestCase):
    def setUp(self):
        self.candidate = OBS.validate_candidate()

    def objects(self):
        cluster = obj("cluster.x-k8s.io/v1beta2", "Cluster", "disposable-ok141", conditions=[
            {"type": "ControlPlaneInitialized", "status": "True", "reason": "Initialized", "observedGeneration": 1}
        ])
        cluster["spec"] = {
            "controlPlaneEndpoint": {"host": "192.0.2.10", "port": 6443},
            "infrastructureRef": {"apiGroup": "infrastructure.cluster.x-k8s.io", "kind": "KubevirtCluster", "name": "disposable-ok141"},
            "controlPlaneRef": {"apiGroup": "controlplane.cluster.x-k8s.io", "kind": "TalosControlPlane", "name": "disposable-ok141-cp"},
        }
        return {
            "cluster": cluster,
            "infrastructure-cluster": obj("infrastructure.cluster.x-k8s.io/v1alpha1", "KubevirtCluster", "disposable-ok141"),
            "control-plane": obj("controlplane.cluster.x-k8s.io/v1alpha3", "TalosControlPlane", "disposable-ok141-cp"),
            "workers": obj("cluster.x-k8s.io/v1beta2", "MachineDeployment", "disposable-ok141-workers"),
        }

    def test_candidate_is_inert_and_exact(self):
        spec = self.candidate["spec"]
        self.assertEqual([q["id"] for q in spec["observation"]["queries"]], ["cluster", "infrastructure-cluster", "control-plane", "workers"])
        self.assertTrue(all(not value for key, value in spec["authorization"].items() if key.endswith("Granted")))
        self.assertFalse(spec["acceptance"]["nodeReadyRequired"])

    def test_current_control_plane_initialized_passes(self):
        state, details = OBS.evaluate(self.candidate, self.objects())
        self.assertEqual(state, "PASS-CURRENT-LIFECYCLE-API-EVIDENCE")
        self.assertTrue(details["endpoint"]["present"])
        self.assertNotIn("host", details["endpoint"])

    def test_stale_or_missing_condition_waits(self):
        for mutation in ("stale-status", "stale-condition", "missing-condition", "missing-endpoint"):
            values = self.objects()
            if mutation == "stale-status":
                values["cluster"]["status"]["observedGeneration"] = 0
            elif mutation == "stale-condition":
                values["cluster"]["status"]["conditions"][0]["observedGeneration"] = 0
            elif mutation == "missing-condition":
                values["cluster"]["status"]["conditions"] = []
            else:
                values["cluster"]["spec"]["controlPlaneEndpoint"] = {}
            state, _ = OBS.evaluate(self.candidate, values)
            self.assertTrue(state.startswith("WAIT-"), (mutation, state))

    def test_wrong_revision_reference_or_identity_fails(self):
        mutations = []
        revision = self.objects()
        revision["workers"]["metadata"]["annotations"]["openkubes.io/intent-revision"] = "sha256:" + "0" * 64
        mutations.append(revision)
        reference = self.objects()
        reference["cluster"]["spec"]["controlPlaneRef"]["name"] = "other"
        mutations.append(reference)
        identity = self.objects()
        identity["control-plane"]["metadata"]["name"] = "other"
        mutations.append(identity)
        for values in mutations:
            state, _ = OBS.evaluate(self.candidate, values)
            self.assertTrue(state.startswith("FAIL-"), state)

    def test_grant_requires_exact_g1_predecessors_and_read_only_authority(self):
        now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)
        grant = {
            "apiVersion": "authorization.openkubes.io/v1alpha1",
            "kind": "GO1LLifecycleAPIObserverGrant",
            "metadata": {"name": "test", "ticket": "OK-141"},
            "spec": {
                "decision": "GO", "candidateDigest": OBS.digest(OBS.CANDIDATE),
                "protocolDigest": self.candidate["spec"]["protocol"]["digest"],
                "fixtureDigest": self.candidate["spec"]["protocol"]["fixtureDigest"],
                "runtimePackageDigest": self.candidate["spec"]["runtimePackage"]["digest"],
                "credentialIdentityDigest": self.candidate["spec"]["credential"]["identityDigest"],
                "authority": "github:arashkaffamanesh", "grantID": "test", "singleRun": True, "consumed": False,
                "issuedAt": "2026-08-14T11:50:00Z", "expiresAt": "2026-08-14T12:30:00Z",
                "outputPath": self.candidate["spec"]["observation"]["outputPath"],
                "g1OperationEvidenceDigests": {key: "sha256:" + str(index) * 64 for index, key in enumerate(("provider-prerequisites", "management-namespace", "provider-access-secret", "capi-lifecycle"), 1)},
                "clusterContactGranted": True, "credentialUseGranted": True, "readOnlyObserverGranted": True,
                "mutationGranted": False, "g3Granted": False, "go1Granted": False, "retryGranted": False,
                "rollbackOrCleanupGranted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "grant.yaml"
            path.write_text(yaml.safe_dump(grant, sort_keys=False))
            OBS.validate_grant(OBS.CANDIDATE, path, now)
            changed = copy.deepcopy(grant)
            changed["spec"]["mutationGranted"] = True
            path.write_text(yaml.safe_dump(changed, sort_keys=False))
            with self.assertRaises(OBS.ObserverError):
                OBS.validate_grant(OBS.CANDIDATE, path, now)

    def test_evidence_redaction_retains_no_endpoint_host_or_full_object(self):
        state, details = OBS.evaluate(self.candidate, self.objects())
        encoded = json.dumps(details)
        self.assertEqual(state, "PASS-CURRENT-LIFECYCLE-API-EVIDENCE")
        self.assertNotIn("192.0.2.10", encoded)
        self.assertNotIn("spec", details["objects"]["cluster"])
        self.assertNotIn("message", encoded)


if __name__ == "__main__":
    unittest.main()
