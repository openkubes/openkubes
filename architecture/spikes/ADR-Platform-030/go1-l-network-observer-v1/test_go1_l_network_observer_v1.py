import copy
import datetime as dt
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("ok141_network_observer_test", HERE / "bounded_go1_l_network_observer_v1.py")
OBS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = OBS
assert SPEC.loader is not None
SPEC.loader.exec_module(OBS)


R = "sha256:166504ae61fd558d391daedde50986cbc7a28f5f4e9d57f4acbd0433b448aa0f"
E = "sha256:2a849d69e9c64344e907c1bce3bb1abf3d8f77217377081a5be055d62c213300"


def current_conditions(*types):
    return [{"type": item, "status": "True", "reason": "Ready", "observedGeneration": 1} for item in types]


def controller(api, kind, name, conditions, status=None):
    value = {"apiVersion": api, "kind": kind, "metadata": {"name": name, "namespace": "disposable-ok141", "uid": f"uid-{name}", "generation": 1}, "status": {"observedGeneration": 1, "conditions": current_conditions(*conditions)}}
    value["status"].update(status or {})
    return value


class NetworkObserverTests(unittest.TestCase):
    def setUp(self):
        self.candidate = OBS.validate_candidate()
        self.hcp_source = OBS.read_yaml(HERE.parent / "go1-l-hcp-v1" / "helmchartproxy-phase-r-v5-candidate.yaml")

    def management(self):
        cluster = controller("cluster.x-k8s.io/v1beta2", "Cluster", "disposable-ok141", [])
        cluster["spec"] = {"controlPlaneEndpoint": {"host": "192.0.2.15", "port": 6443}}
        hcp = copy.deepcopy(self.hcp_source)
        hcp["metadata"].update({"uid": "uid-hcp", "generation": 1})
        hcp["status"] = {"observedGeneration": 1, "matchingClusters": [{"name": "disposable-ok141", "namespace": "disposable-ok141"}], "conditions": current_conditions("Ready", "HelmReleaseProxySpecsUpToDate", "HelmReleaseProxiesReady")}
        hrp = controller("addons.cluster.x-k8s.io/v1alpha1", "HelmReleaseProxy", "cilium-disposable-ok141-x", ["Ready", "HelmReleaseReady"], {"status": "deployed", "revision": 1})
        hrp["metadata"]["labels"] = {"cluster.x-k8s.io/cluster-name": "disposable-ok141", "helmreleaseproxy.addons.cluster.x-k8s.io/helmchartproxy-name": "disposable-ok141-cilium"}
        hrp["metadata"]["ownerReferences"] = [{"apiVersion": "addons.cluster.x-k8s.io/v1alpha1", "kind": "HelmChartProxy", "name": "disposable-ok141-cilium", "uid": "uid-hcp", "controller": True}]
        hrp["spec"] = {"clusterRef": {"apiVersion": "cluster.x-k8s.io/v1beta2", "kind": "Cluster", "namespace": "disposable-ok141", "name": "disposable-ok141"}, "chartName": "cilium", "repoURL": "oci://quay.io/cilium/charts", "version": "1.19.6", "releaseName": "cilium", "namespace": "kube-system", "reconcileStrategy": "Continuous", "values": hcp["spec"]["valuesTemplate"]}
        secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "disposable-ok141-kubeconfig", "namespace": "disposable-ok141"}, "data": {"value": "dGVzdA=="}}
        return {"cluster": cluster, "hcp": hcp, "hrp": {"items": [hrp]}, "workload-kubeconfig": secret}

    def lifecycle(self):
        return {"closureState": "PASS-CURRENT-LIFECYCLE-API-EVIDENCE", "details": {"objects": {"cluster": {"uid": "uid-disposable-ok141"}}}}

    def workload(self):
        nodes = []
        for index in (0, 1):
            nodes.append({"apiVersion": "v1", "kind": "Node", "metadata": {"name": f"node-{index}", "uid": f"node-uid-{index}"}, "spec": {"providerID": f"kubevirt://node-{index}"}, "status": {"conditions": [{"type": "Ready", "status": "True"}, {"type": "NetworkUnavailable", "status": "False", "reason": "CiliumIsUp"}]}})
        def daemon(name, container, image):
            return {"apiVersion": "apps/v1", "kind": "DaemonSet", "metadata": {"name": name, "namespace": "kube-system", "uid": f"uid-{name}", "generation": 1}, "spec": {"template": {"spec": {"containers": [{"name": container, "image": image}]}}}, "status": {"observedGeneration": 1, "desiredNumberScheduled": 2, "updatedNumberScheduled": 2, "numberAvailable": 2, "numberReady": 2}}
        images = self.candidate["spec"]["workload"]["expectedImages"]
        operator = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "cilium-operator", "namespace": "kube-system", "uid": "uid-operator", "generation": 1}, "spec": {"template": {"spec": {"containers": [{"name": "cilium-operator", "image": images["cilium-operator"]}]}}}, "status": {"observedGeneration": 1, "availableReplicas": 1, "updatedReplicas": 1}}
        pods = []
        for index in (0, 1):
            pods.append({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": f"cilium-{index}", "namespace": "kube-system", "uid": f"pod-uid-{index}"}, "spec": {"nodeName": f"node-{index}"}, "status": {"phase": "Running", "containerStatuses": [{"name": "cilium-agent", "ready": True}]}})
        return {"nodes": {"items": nodes}, "cilium-daemonset": daemon("cilium", "cilium-agent", images["cilium-agent"]), "envoy-daemonset": daemon("cilium-envoy", "cilium-envoy", images["cilium-envoy"]), "cilium-operator": operator, "cilium-pods": {"items": pods}}

    def test_candidate_is_inert_and_binds_fixed_probe(self):
        spec = self.candidate["spec"]
        self.assertEqual(spec["sources"]["cilium"]["functionalProbe"], ["cilium-health", "status", "--probe", "--output", "json"])
        self.assertTrue(all(not value for key, value in spec["authorization"].items() if key.endswith("Granted")))
        self.assertEqual(spec["management"]["queries"][-1]["mode"], "exact-secret")

    def test_management_chain_passes_and_redacts_secret_from_details_after_consumer(self):
        state, details = OBS.evaluate_management(self.candidate, self.management(), self.lifecycle(), self.hcp_source)
        self.assertEqual(state, "PASS-MANAGEMENT-ENABLEMENT")
        self.assertEqual(details["kubeconfigData"], "dGVzdA==")
        self.assertEqual(details["hcpUID"], "uid-hcp")

    def test_management_fails_wrong_owner_revision_or_count(self):
        cases = []
        wrong_owner = self.management()
        wrong_owner["hrp"]["items"][0]["metadata"]["ownerReferences"][0]["uid"] = "wrong"
        cases.append(wrong_owner)
        wrong_revision = self.management()
        wrong_revision["hcp"]["metadata"]["annotations"]["openkubes.io/enablement-revision"] = "sha256:" + "0" * 64
        cases.append(wrong_revision)
        wrong_count = self.management()
        wrong_count["hrp"]["items"].append(copy.deepcopy(wrong_count["hrp"]["items"][0]))
        cases.append(wrong_count)
        wrong_hcp_spec = self.management()
        wrong_hcp_spec["hcp"]["spec"]["valuesTemplate"] += "\nchanged: true"
        cases.append(wrong_hcp_spec)
        states = [OBS.evaluate_management(self.candidate, value, self.lifecycle(), self.hcp_source)[0] for value in cases]
        self.assertTrue(states[0].startswith("FAIL-"))
        self.assertTrue(states[1].startswith("FAIL-"))
        self.assertEqual(states[2], "WAIT-EXACTLY-ONE-HRP")
        self.assertEqual(states[3], "FAIL-HCP-SPEC")

    def test_static_network_sources_pass(self):
        state, details = OBS.evaluate_workload(self.candidate, self.workload())
        self.assertEqual(state, "PASS-STATIC-NETWORK-SOURCES")
        self.assertEqual(details["nodeNames"], ["node-0", "node-1"])
        self.assertEqual(details["probePod"]["name"], "cilium-0")

    def test_static_sources_fail_closed_for_node_rollout_and_image(self):
        node = self.workload()
        node["nodes"]["items"][0]["status"]["conditions"][1]["reason"] = "Other"
        rollout = self.workload()
        rollout["cilium-daemonset"]["status"]["numberReady"] = 1
        image = self.workload()
        image["cilium-operator"]["spec"]["template"]["spec"]["containers"][0]["image"] = "mutable:latest"
        self.assertEqual(OBS.evaluate_workload(self.candidate, node)[0], "WAIT-NODE-NETWORK")
        self.assertEqual(OBS.evaluate_workload(self.candidate, rollout)[0], "WAIT-CILIUM-ROLLOUT")
        self.assertEqual(OBS.evaluate_workload(self.candidate, image)[0], "FAIL-CILIUM-IMAGE")

    def probe(self, status="", timestamp="2026-08-14T12:00:00Z"):
        path = {"http": {"status": status, "lastProbed": timestamp}, "icmp": {"status": status, "lastProbed": timestamp}}
        return {"timestamp": timestamp, "nodes": [{"name": name, "host": {"primary-address": copy.deepcopy(path)}, "health-endpoint": {"primary-address": copy.deepcopy(path)}} for name in ("node-0", "node-1")]}

    def test_functional_probe_requires_all_http_and_icmp_paths(self):
        now = dt.datetime(2026, 8, 14, 12, 0, 30, tzinfo=dt.timezone.utc)
        state, details = OBS.evaluate_probe(self.probe(), ["node-0", "node-1"], now, 120)
        self.assertEqual(state, "PASS-FUNCTIONAL-NETWORK-PROBE")
        self.assertEqual(details["successfulPathCount"], 8)
        self.assertEqual(OBS.evaluate_probe(self.probe("timeout"), ["node-0", "node-1"], now, 120)[0], "FAIL-FUNCTIONAL-CONNECTIVITY")
        self.assertEqual(OBS.evaluate_probe(self.probe(timestamp="2026-08-14T11:55:00Z"), ["node-0", "node-1"], now, 120)[0], "FAIL-STALE-FUNCTIONAL-PROBE")
        mixed = self.probe()
        mixed["nodes"][0]["host"]["primary-address"]["http"]["lastProbed"] = "2026-08-14T11:55:00Z"
        self.assertEqual(OBS.evaluate_probe(mixed, ["node-0", "node-1"], now, 120)[0], "FAIL-STALE-FUNCTIONAL-PATH")

    def test_grant_requires_secret_read_and_fixed_exec_but_no_persistent_mutation(self):
        now = dt.datetime(2026, 8, 14, 12, 0, tzinfo=dt.timezone.utc)
        spec = {
            "decision": "GO", "candidateDigest": OBS.digest(OBS.CANDIDATE), "protocolDigest": self.candidate["spec"]["protocol"]["digest"], "fixtureDigest": self.candidate["spec"]["protocol"]["fixtureDigest"],
            "authority": "github:arashkaffamanesh", "grantID": "test", "singleRun": True, "consumed": False,
            "issuedAt": "2026-08-14T11:55:00Z", "expiresAt": "2026-08-14T12:30:00Z", "outputPath": self.candidate["spec"]["observation"]["outputPath"],
            "lifecycleEvidenceDigest": "sha256:" + "1" * 64, "hcpSubmissionEvidenceDigest": "sha256:" + "2" * 64,
            "clusterContactGranted": True, "managementCredentialUseGranted": True, "workloadKubeconfigSecretReadGranted": True,
            "ephemeralCredentialMaterializationGranted": True, "workloadCredentialUseGranted": True, "readOnlyQueriesGranted": True, "fixedPodExecProbeGranted": True,
            "persistentMutationGranted": False, "retryGranted": False, "rollbackOrCleanupGranted": False, "go1Granted": False, "evidencePublicationGranted": False, "failureInjectionGranted": False,
        }
        grant = {"apiVersion": "authorization.openkubes.io/v1alpha1", "kind": "GO1LNetworkReadyObserverGrant", "metadata": {"name": "test"}, "spec": spec}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "grant.yaml"
            path.write_text(yaml.safe_dump(grant, sort_keys=False))
            OBS.validate_grant(OBS.CANDIDATE, path, now)
            changed = copy.deepcopy(grant)
            changed["spec"]["persistentMutationGranted"] = True
            path.write_text(yaml.safe_dump(changed, sort_keys=False))
            with self.assertRaises(OBS.NetworkObserverError):
                OBS.validate_grant(OBS.CANDIDATE, path, now)


if __name__ == "__main__":
    unittest.main()
