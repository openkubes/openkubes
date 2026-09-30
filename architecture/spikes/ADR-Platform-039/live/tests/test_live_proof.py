import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from probes import live_proof as proof


TEST_CLUSTER_UID = "test-cluster-uid"  # the real kube-system UID is pinned only as a hash


class HarnessTests(unittest.TestCase):
    BINDINGS = {name: "e" * 64 for name in ("documentsSha256", "rendersSha256", "appliedObjectsSha256", "overlaysSha256", "cleanupLedgerSha256")}
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "OK174_OPENCODE_IMAGE": "registry.invalid/opencode@sha256:" + "a" * 64,
            "OK174_CODEX_IMAGE": "registry.invalid/codex@sha256:" + "b" * 64,
            "OK174_FIXTURE_IMAGE": "registry.invalid/fixture@sha256:" + "c" * 64,
        }, clear=False)
        self.env.start()
        self.pin = patch.object(proof, "TARGET_CLUSTER_UID_SHA256", proof.sha(TEST_CLUSTER_UID)); self.pin.start()
        self.vpin = patch.dict(proof.renderer().CLUSTER_UID_SHA256_PINS, {proof.TARGET_CONTEXT: proof.sha(TEST_CLUSTER_UID)}); self.vpin.start()

    def tearDown(self):
        self.vpin.stop(); self.pin.stop(); self.env.stop()

    def test_two_documents_differ_only_at_runtime_profile(self):
        pair = proof.rendered_pair("a" * 40)
        left, right = copy.deepcopy(pair["opencode"][0]), copy.deepcopy(pair["codex"][0])
        self.assertEqual(left["spec"].pop("runtime"), {"profile": "opencode"})
        self.assertEqual(right["spec"].pop("runtime"), {"profile": "codex"})
        self.assertEqual(left, right)
        self.assertEqual(pair["opencode"][2]["kind"], "DeveloperWorkspaceNamespaceRender")

    def test_overlay_has_only_operational_labels_and_pull_secret(self):
        _, _, rendered = proof.rendered_workspace("opencode", "a" * 40)
        objects, ledger = proof.overlay(rendered, "run-1")
        deploy = next(x for x in objects if x["kind"] == "Deployment")
        self.assertEqual(deploy["spec"]["template"]["spec"]["imagePullSecrets"], [{"name": proof.REGISTRY_PULL_SECRET}])
        allowed = {"metadata.labels", "spec.template.metadata.labels", "spec.template.spec.imagePullSecrets"}
        self.assertTrue(all(set(x["overlays"]).issubset(allowed) for x in ledger))

    def test_readback_rejects_each_rendered_kind_when_drifted(self):
        _, _, rendered = proof.rendered_workspace("opencode", "a" * 40)
        expected, _ = proof.overlay(rendered, "run-1")
        kinds = ("Namespace", "Deployment", "NetworkPolicy", "ResourceQuota", "PersistentVolumeClaim", "ServiceAccount", "LimitRange")
        actual = {kind.lower(): [proof.normalized(x) for x in expected if x["kind"] == kind] for kind in kinds}
        class K:
            def run(self, args, **_): return json.dumps(actual["namespace"][0] if args[1] == "namespace" else {"items": actual[args[1]]})
        proof.readback_contract(K(), proof.NAMESPACE, expected)
        for kind in actual:
            if not actual[kind]:
                continue
            bad = copy.deepcopy(actual); bad[kind][0]["metadata"]["name"] = "wrong"
            class Broken:
                def run(self, args, **_): return json.dumps(bad["namespace"][0] if args[1] == "namespace" else {"items": bad[args[1]]})
            with self.subTest(kind=kind):
                with self.assertRaises(proof.ProofError): proof.readback_contract(Broken(), proof.NAMESPACE, expected)
        injected = copy.deepcopy(actual)
        injected["deployment"][0]["spec"]["template"]["spec"]["containers"][0]["envFrom"] = [{"secretRef": {"name": "workspace-git-auth"}}]
        class Injected:
            def run(self, args, **_): return json.dumps(injected["namespace"][0] if args[1] == "namespace" else {"items": injected[args[1]]})
        with self.assertRaises(proof.ProofError): proof.readback_contract(Injected(), proof.NAMESPACE, expected)
        privileged = copy.deepcopy(actual)
        privileged["deployment"][0]["spec"]["template"]["spec"]["containers"][0]["securityContext"]["privileged"] = True
        class Privileged:
            def run(self, args, **_): return json.dumps(privileged["namespace"][0] if args[1] == "namespace" else {"items": privileged[args[1]]})
        with self.assertRaises(proof.ProofError): proof.readback_contract(Privileged(), proof.NAMESPACE, expected)
        for extra, allowed in (("default", True), ("sidecar", False)):
            more = copy.deepcopy(actual); more["serviceaccount"].append({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": extra, "namespace": proof.NAMESPACE}})
            class More:
                def run(self, args, **_): return json.dumps(more["namespace"][0] if args[1] == "namespace" else {"items": more[args[1]]})
            with self.subTest(extra=extra):
                if allowed: proof.readback_contract(More(), proof.NAMESPACE, expected)
                else:
                    with self.assertRaises(proof.ProofError): proof.readback_contract(More(), proof.NAMESPACE, expected)

    def test_runtime_credential_predicate_turns_red(self):
        deployment = {"spec": {"template": {"spec": {"containers": [{"env": []}]}}}}
        self.assertFalse(proof.runtime_has_credential(deployment))
        deployment["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "GIT_AUTH_TOKEN"})
        self.assertTrue(proof.runtime_has_credential(deployment))

    def test_rbac_list_predicate_turns_red(self):
        self.assertTrue(proof.rbac_list_denied("Resources Non-Resource URLs Resource Names Verbs\n"))
        self.assertTrue(proof.rbac_list_denied("selfsubjectrulesreviews.authorization.k8s.io [] [] [create]"))
        discovery = """Resources  Non-Resource URLs  Resource Names  Verbs
selfsubjectaccessreviews.authorization.k8s.io  []  []  [create]
  [/api /api/* /apis /apis/* /openapi /openapi/*]  []  [get]
  [/.well-known/openid-configuration /openid/v1/jwks]  []  [get]
"""
        self.assertTrue(proof.rbac_list_denied(discovery))
        self.assertFalse(proof.rbac_list_denied("pods [] [] [get]"))
        self.assertFalse(proof.rbac_list_denied("pods selfsubjectaccessreviews.authorization.k8s.io [] [] [get]"))
        self.assertFalse(proof.rbac_list_denied("deployments [/api] [] [get]"))
        self.assertFalse(proof.rbac_list_denied("secrets [] [] [get list]"))
        self.assertFalse(proof.rbac_list_denied("*.* [] [] [*]"))

    def test_image_id_exact_digest_predicate_turns_red(self):
        approved = os.environ["OK174_OPENCODE_IMAGE"]
        pod = {"spec": {"containers": [{"name": "runtime", "image": approved}]}, "status": {"containerStatuses": [{"name": "runtime", "imageID": approved}]}}
        self.assertEqual(proof.exact_image_id(pod, approved), approved)
        pod["status"]["containerStatuses"][0]["imageID"] = "NOT-RUN " + approved
        with self.assertRaises(proof.ProofError): proof.exact_image_id(pod, approved)
        pod["status"]["containerStatuses"][0]["imageID"] = "registry.invalid/opencode@sha256:" + "e" * 64
        with self.assertRaises(proof.ProofError): proof.exact_image_id(pod, approved)

    def test_denied_egress_polarity_turns_red(self):
        self.assertTrue(proof.denied_egress(7, "failed to connect"))
        self.assertTrue(proof.denied_egress(28, "timed out"))
        self.assertFalse(proof.denied_egress(0, ""))
        self.assertFalse(proof.denied_egress(22, "HTTP 403"))
        self.assertFalse(proof.denied_egress(6, "could not resolve"))

    def test_raw_transcript_hash_binding_turns_red(self):
        with tempfile.TemporaryDirectory() as directory:
            binding = proof.capture(Path(directory), "can-i", CompletedProcess(["kubectl"], 0, "no", ""))
            run = {"kind": "DeveloperWorkspaceProbeRun", "bindings": dict(self.BINDINGS), "results": [
                {"name": name, "status": "PASS", "detail": "captured", "evidence": {}}
                for name in proof.RESULT_NAMES
            ], "rawEvidence": {"rbac": binding}}
            proof.validate_run(run)
            Path(binding["path"]).write_text("tampered")
            with self.assertRaises(proof.ProofError): proof.validate_run(run)

    def test_capture_redacts_and_flags_plain_and_encoded_canary(self):
        with tempfile.TemporaryDirectory() as directory:
            proof.configure_capture_redaction("credential-canary")
            encoded = "Y3JlZGVudGlhbC1jYW5hcnk="
            binding = proof.capture(Path(directory), "leak", CompletedProcess(["probe"], 0, "credential-canary " + encoded, ""))
            content = Path(binding["path"]).read_text()
            self.assertNotIn("credential-canary", content)
            self.assertNotIn(encoded, content)
            self.assertEqual(proof.CAPTURE_LEAKS, ["leak", "leak"])
            proof.configure_capture_redaction("")

    def test_result_writer_rejects_missing_or_failed_named_result(self):
        complete = {"kind": "DeveloperWorkspaceProbeRun", "bindings": dict(self.BINDINGS), "results": [
            {"name": name, "status": "PASS", "detail": "captured", "evidence": {}}
            for name in proof.RESULT_NAMES
        ], "rawEvidence": {}}
        proof.validate_run(complete)
        missing = copy.deepcopy(complete)
        missing["results"].pop()
        with self.assertRaises(proof.ProofError): proof.validate_run(missing)
        failed = copy.deepcopy(complete)
        failed["results"][0]["status"] = "SKIPPED"
        with self.assertRaises(proof.ProofError): proof.validate_run(failed)

    def test_agent_event_requires_exact_verification_tool_evidence(self):
        with self.assertRaises(proof.ProofError):
            proof.validate_agent_events("opencode", json.dumps({"type": "text", "part": {"text": "I ran it"}}), ["sh", "-ec", "true"])
        events = "\n".join((
            json.dumps({"type": "step_start", "sessionID": "session-opencode", "part": {}}),
            json.dumps({"type": "tool_use", "sessionID": "session-opencode", "part": {"callID": "edit-1", "tool": "write", "state": {"status": "completed", "input": {"command": "printf mutation > README.md"}, "output": "changed"}}}),
            json.dumps({"type": "tool_use", "sessionID": "session-opencode", "part": {"callID": "exec-1", "tool": "bash", "state": {"status": "completed", "input": {"command": "sh -ec true"}, "output": "passed", "metadata": {"exit": 0}}}}),
            json.dumps({"type": "step_finish", "sessionID": "session-opencode", "part": {"reason": "stop"}}),
        ))
        proof.validate_agent_events("opencode", events, ["sh", "-ec", "true"])
        generic = "\n".join((json.dumps({"type": "tool", "id": "edit-generic", "name": "write", "status": "completed", "output": "changed", "command": "printf mutation > README.md"}), json.dumps({"type": "tool", "id": "exec-generic", "name": "exec", "status": "completed", "output": "passed", "command": "sh -ec true"})))
        for runtime in ("opencode", "codex"):
            with self.assertRaises(proof.ProofError): proof.validate_agent_events(runtime, generic, ["sh", "-ec", "true"])
        split = "\n".join((json.dumps({"type": "tool", "name": "write", "command": "printf mutation > README.md"}), json.dumps({"type": "message", "text": {"command": "sh -ec true"}})))
        with self.assertRaises(proof.ProofError): proof.validate_agent_events("opencode", split, ["sh", "-ec", "true"])
        with self.assertRaises(proof.ProofError):
            proof.validate_agent_events("opencode", events, ["sh", "-ec", "false"])
        failed_shell = "\n".join((
            json.dumps({"type": "step_start", "sessionID": "session-failed", "part": {}}),
            json.dumps({"type": "tool_use", "sessionID": "session-failed", "part": {"callID": "edit-failed", "tool": "write", "state": {"status": "completed", "input": {"command": "printf mutation > README.md"}, "output": "changed"}}}),
            json.dumps({"type": "tool_use", "sessionID": "session-failed", "part": {"callID": "exec-failed", "tool": "bash", "state": {"status": "completed", "input": {"command": "sh -ec true"}, "output": "command failed with exit code 1", "metadata": {"exit": 1}}}}),
            json.dumps({"type": "step_finish", "sessionID": "session-failed", "part": {"reason": "stop"}}),
        ))
        with self.assertRaises(proof.ProofError): proof.validate_agent_events("opencode", failed_shell, ["sh", "-ec", "true"])
        contradictory = failed_shell.replace('"exit": 1', '"exit": 0')
        with self.assertRaises(proof.ProofError): proof.validate_agent_events("opencode", contradictory, ["sh", "-ec", "true"])
        non_exec = failed_shell.replace('"tool": "bash"', '"tool": "write"')
        with self.assertRaises(proof.ProofError): proof.validate_agent_events("opencode", non_exec, ["sh", "-ec", "true"])
        unconfirmed = "\n".join((json.dumps({"type": "tool", "name": "write", "command": "printf mutation > README.md"}), json.dumps({"type": "tool", "name": "exec", "command": "sh -ec true"})))
        with self.assertRaises(proof.ProofError):
            proof.validate_agent_events("opencode", unconfirmed, ["sh", "-ec", "true"])
        failed_nested = "\n".join((json.dumps({"type": "item.completed", "item": {"type": "tool", "id": "edit-failed", "name": "write", "status": "failed", "output": "failed", "command": "printf mutation > README.md"}}), json.dumps({"type": "item.completed", "item": {"type": "command_execution", "id": "exec-failed", "status": "failed", "exit_code": 1, "command": "sh -ec true"}})))
        with self.assertRaises(proof.ProofError):
            proof.validate_agent_events("codex", failed_nested, ["sh", "-ec", "true"])
        codex = "\n".join((json.dumps({"type": "item.completed", "item": {"id": "edit-2", "type": "command_execution", "command": "printf mutation > README.md", "aggregated_output": "", "exit_code": 0, "status": "completed"}}), json.dumps({"type": "item.completed", "item": {"id": "exec-2", "type": "command_execution", "command": "sh -ec true", "aggregated_output": "passed", "exit_code": 0, "status": "completed"}}), json.dumps({"type": "turn.completed", "usage": {}})))
        proof.validate_agent_events("codex", codex, ["sh", "-ec", "true"])

    def test_target_cluster_uid_pin_turns_red(self):
        class K:
            def __init__(self, uid): self.uid = uid
            def run(self, args, **_):
                if args[:2] == ["config", "current-context"]: return proof.TARGET_CONTEXT + "\n"
                if args[0] == "version": return json.dumps({"serverVersion": {"gitVersion": "v1.30.0"}})
                if args[:3] == ["get", "namespace", "kube-system"]: return json.dumps({"metadata": {"uid": self.uid}})
                raise AssertionError(args)
        with tempfile.NamedTemporaryFile() as kubeconfig, patch.dict(os.environ, {"KUBECONFIG": kubeconfig.name}, clear=False):
            self.assertEqual(proof.current_target(K(TEST_CLUSTER_UID))["cluster"]["uidSha256"], proof.sha(TEST_CLUSTER_UID))
            with self.assertRaises(proof.ProofError): proof.current_target(K("wrong-cluster"))

    def test_health_projection_ignores_heartbeat_but_detects_status(self):
        node = {"metadata": {"name": "node-a", "uid": "u"}, "spec": {}, "status": {"conditions": [{"type": "Ready", "status": "True", "reason": "KubeletReady", "lastHeartbeatTime": "one"}], "images": [{"name": "volatile"}]}}
        changed = copy.deepcopy(node); changed["status"]["conditions"][0]["lastHeartbeatTime"] = "two"
        self.assertEqual(proof.stable_node_health({"items": [node]}), proof.stable_node_health({"items": [changed]}))
        changed["status"]["conditions"][0]["status"] = "False"
        self.assertNotEqual(proof.stable_node_health({"items": [node]}), proof.stable_node_health({"items": [changed]}))

    def test_fixture_uses_real_tls_secret_only_on_git_deployment(self):
        tls = {"ca": "public-ca", "cert": "public-cert", "key": "private-key"}
        objects = proof.proof_service_objects("a" * 24, tls, b"fixture-token")
        git = next(x for x in objects if x.get("kind") == "Deployment" and x["metadata"]["name"] == "git-fixture")
        self.assertEqual(git["spec"]["template"]["spec"]["volumes"], [{"name": "tls", "secret": {"secretName": "git-fixture-tls"}}])
        self.assertTrue(git["spec"]["template"]["spec"]["containers"][0]["volumeMounts"][0]["readOnly"])
        self.assertEqual(git["spec"]["template"]["spec"]["containers"][0]["env"][-1]["name"], "GIT_AUTH_TOKEN")
        self.assertEqual({x["port"] for x in next(x for x in objects if x.get("kind") == "Service" and x["metadata"]["name"] == "git-fixture")["spec"]["ports"]}, {8080, 8443})
        for name in ("mcp-fixture", "denied-fixture"):
            deployment = next(x for x in objects if x.get("kind") == "Deployment" and x["metadata"]["name"] == name)
            self.assertNotIn("volumes", deployment["spec"]["template"]["spec"])
        self.assertNotIn("ollama", {x["metadata"]["name"] for x in objects})

    def test_storage_eviction_and_candidate_final_separation(self):
        self.assertTrue(proof.denied_egress(7, "blocked"))
        self.assertFalse(proof.denied_egress(0, "eviction is not a network success"))
        _, _, ephemeral = proof.rendered_workspace("opencode", "a" * 40, mode="ephemeral", workspace_id="ws-ok174-ephemeral")
        pod = ephemeral["spec"]["resources"][-1]["spec"]["template"]["spec"]
        self.assertEqual(pod["volumes"][0]["emptyDir"]["sizeLimit"], "8Mi")
        self.assertNotIn("ephemeral-storage", pod["containers"][0]["resources"]["limits"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = {"kind": "DeveloperWorkspaceProbeRun", "runID": "a" * 24,
                         "startedAt": "2026-01-01T00:00:00Z", "finishedAt": "2026-01-01T00:01:00Z",
                         "bindings": dict(self.BINDINGS),
                         "results": [{"name": name, "status": "FAIL", "detail": "expected failure", "evidence": {}} for name in proof.RESULT_NAMES],
                         "rawEvidence": {}, "overlays": [], "mismatches": list(proof.OVERLAY_MISMATCHES), "failures": ["expected failure"]}
            with patch.object(proof, "EVIDENCE_DIR", root), patch.object(proof, "FINAL_EVIDENCE", root / "final.yaml"):
                proof.candidate_path("a" * 24).write_text(json.dumps(candidate))
                state = {"runID": "a" * 24, "startedAt": "2026-01-01T00:00:00Z", "target": {"context": proof.TARGET_CONTEXT, "cluster": {"uid": "u", "version": "v1.30"}, "kubeconfigSha256": "a" * 64},
                         "revision": "a" * 40, "knownCommit": "c" * 40, "profileInputs": {"model": "qwen", "storageClassName": "local-path", "images": proof.images()},
                         "git": {"head": "a" * 40, "worktreeClean": True, "gitStatusSha256": "b" * 64, "implementationTreeSha256": proof.renderer().implementation_tree_sha256()}, "bindings": dict(self.BINDINGS), "overlays": []}
                with self.assertRaises(proof.ProofError): proof.write_evidence(state)
                self.assertFalse((root / "final.yaml").exists())

    def test_revise_evidence_is_schema_and_semantic_valid_with_raw_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(proof, "EVIDENCE_DIR", root):
                binding = proof.capture(root / "raw" / ("a" * 24), "failure", CompletedProcess(["kubectl"], 1, "", "failed"))
                candidate = {"bindings": dict(self.BINDINGS), "results": [{"name": name, "status": "FAIL", "detail": "effect failed", "evidence": {"failure": "effect failed"}} for name in proof.RESULT_NAMES],
                             "rawEvidence": {"failure": binding}, "mismatches": list(proof.OVERLAY_MISMATCHES)}
                state = {"runID": "a" * 24, "target": {"context": proof.TARGET_CONTEXT, "cluster": {"uidSha256": proof.sha(TEST_CLUSTER_UID), "version": "v1.30.0"}, "kubeconfigSha256": "a" * 64},
                         "revision": "a" * 40, "knownCommit": "c" * 40, "profileInputs": {"model": "ok174-gpt-oss:20b", "storageClassName": "local-path", "images": proof.images()},
                         "git": {"head": "a" * 40, "worktreeClean": True, "gitStatusSha256": "b" * 64, "implementationTreeSha256": proof.renderer().implementation_tree_sha256()}, "overlays": []}
                candidate = {**candidate, "startedAt": "2026-01-01T00:00:00Z", "finishedAt": "2026-01-01T00:01:00Z"}
                evidence = proof.final_evidence(state, candidate)
                candidate["bindings"] = {**proof.renderer().expected_live_bindings(evidence["spec"]), "cleanupLedgerSha256": self.BINDINGS["cleanupLedgerSha256"]}
                evidence = proof.final_evidence(state, candidate)
                proof.renderer().validate_live_evidence(evidence, root)
                self.assertEqual(evidence["spec"]["status"], "REVISE")
                self.assertEqual(evidence["spec"]["mismatches"], list(proof.OVERLAY_MISMATCHES))

    def test_cleanup_uses_state_recorded_uids_not_labels(self):
        class K:
            def __init__(self): self.deletes = []
            def run(self, args, **_):
                if args[:2] == ["get", "namespace"]:
                    return json.dumps({"metadata": {"uid": {proof.PROOF_NAMESPACE: "proof", proof.NAMESPACE: "workspace", proof.EVIDENCE_NAMESPACE: "evidence"}[args[2]]}})
                if args[:2] == ["get", "pv"]: return json.dumps({"items": []})
                raise AssertionError(args)
            def result(self, args, input_text=None, **_):
                if args[:2] == ["delete", "--raw"]:
                    self.deletes.append((args, json.loads(input_text)))
                    return CompletedProcess(args, 0, json.dumps({"kind": "Namespace", "metadata": {"uid": json.loads(input_text)["preconditions"]["uid"]}}), "")
                if args[:2] == ["get", "namespace"]: return CompletedProcess(args, 1, "", "NotFound")
                raise AssertionError(args)
        state = {"namespaceUIDs": {proof.PROOF_NAMESPACE: "proof", proof.NAMESPACE: "workspace", proof.EVIDENCE_NAMESPACE: "evidence"}, "persistentPVUID": "gone"}
        k = K(); deleted = proof.clean_workspaces(k, state, approve_checked=True)
        self.assertEqual(deleted["pvUID"], "gone")
        self.assertEqual({a[2]: body["preconditions"]["uid"] for a, body in k.deletes}, {"/api/v1/namespaces/" + n: u for n, u in state["namespaceUIDs"].items()})
        broken = copy.deepcopy(state); broken["namespaceUIDs"][proof.NAMESPACE] = "different"
        with self.assertRaises(proof.ProofError): proof.clean_workspaces(K(), broken, approve_checked=True)

    def test_scripted_fake_kubectl_exercises_probe_candidate_phase(self):
        """An unavailable effect becomes a complete REVISE candidate, never a two-result PASS."""
        pair = proof.rendered_pair("a" * 40)
        class K:
            def result(self, args, **_):
                return CompletedProcess(["kubectl", *args], 1, "", "scripted fake failure")
            def run(self, args, **kwargs):
                completed = self.result(args, **kwargs)
                if completed.returncode:
                    raise proof.ProofError("scripted fake failure")
                return completed.stdout
            def apply(self, _objects):
                raise proof.ProofError("scripted fake apply failure")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {
                "runID": "a" * 24, "phase": "applied", "startedAt": "2026-01-01T00:00:00Z",
                "revision": "a" * 40, "documents": {name: value[0] for name, value in pair.items()},
                "knownCommit": "a" * 40,
                "renders": {name: value[2] for name, value in pair.items()}, "overlays": [],
                "bindings": dict(self.BINDINGS),
                "healthBefore": {"sha256": "x", "capture": {}}, "namespaceUIDs": {},
                "canarySha256": "x",
            }
            with patch.object(proof, "RAW_DIR", root / "raw"), patch.object(proof, "EVIDENCE_DIR", root), patch.object(proof, "STATE_DIR", root / "state"), patch.object(proof, "git_clean_revision", return_value={}):
                state["git"] = {}
                run = proof.probe(K(), state)
            self.assertEqual([item["name"] for item in run["results"]], list(proof.RESULT_NAMES))
            self.assertTrue(any(item["status"] == "FAIL" for item in run["results"]))
            self.assertEqual(run["mismatches"], list(proof.OVERLAY_MISMATCHES))
            self.assertEqual(len(run["failures"]), sum(item["status"] == "FAIL" for item in run["results"]))
            self.assertTrue((root / ("a" * 24 + ".candidate.json")).is_file())

    def test_quota_message_must_name_requests_storage(self):
        proof.quota_rejects_storage(CompletedProcess(["kubectl"], 1, "", "exceeded quota: requests.storage"))
        with self.assertRaises(proof.ProofError):
            proof.quota_rejects_storage(CompletedProcess(["kubectl"], 1, "", "exceeded quota: limits.cpu"))

    def test_persistence_requires_new_pod_uid_and_source_requires_known_commit(self):
        proof.persistence_binding("hash", "hash", "old", "new", "pvc", "pvc", "pv", "pv")
        with self.assertRaises(proof.ProofError): proof.persistence_binding("hash", "hash", "same", "same", "pvc", "pvc", "pv", "pv")
        with self.assertRaises(proof.ProofError): proof.source_matches("a" * 40, "b" * 40)

    def test_state_persists_and_probe_requires_applied_state(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(proof, "STATE_DIR", Path(directory)):
            proof.write_state({"runID": "a" * 24, "phase": "applied"})
            self.assertEqual(proof.read_state("a" * 24)["phase"], "applied")
            Path(directory, "b" * 24 + ".json").write_text(json.dumps({"runID": "b" * 24, "phase": "created"}))
            with self.assertRaises(proof.ProofError): proof.read_state("b" * 24)

    def test_negative_controls_go_red_on_fault_and_green_after_revert(self):
        state = {"runID": "d" * 24, "phase": "applied", "revision": "c" * 40, "git": {"head": "c" * 40, "implementationTreeSha256": proof.renderer().implementation_tree_sha256()}, "target": {"context": proof.TARGET_CONTEXT, "cluster": {"uidSha256": proof.sha(TEST_CLUSTER_UID), "version": "v1.34.1"}},
                 "renders": {"opencode": proof.rendered_workspace("opencode", "a" * 40)[2]}, "namespaceUIDs": {proof.PROOF_NAMESPACE: "u1", proof.NAMESPACE: "u2", proof.EVIDENCE_NAMESPACE: "u3"}}
        expected, _ = proof.overlay(state["renders"]["opencode"], state["runID"])
        canary = "canary-value-0123456789abcdef"
        live = {"token": False, "automount": False, "role": False, "nps": set(), "quota": "1Gi", "planted": False, "deleted": set()}
        def ok(out=""): return (0, out, "")
        def run(args, input=None, **_):
            a = args[1:]
            if a[:2] == ["config", "current-context"]: r = ok(proof.TARGET_CONTEXT)
            elif a[:1] == ["version"]: r = ok(json.dumps({"serverVersion": {"gitVersion": "v1.34.1"}}))
            elif a[:3] == ["get", "namespace", "kube-system"]: r = ok(json.dumps({"metadata": {"uid": TEST_CLUSTER_UID}}))
            elif a[:3] == ["get", "secret", "workspace-git-auth"]: r = ok(json.dumps({"data": {"token": __import__("base64").b64encode(canary.encode()).decode()}}))
            elif a[:2] == ["get", "pods"]: r = ok(json.dumps({"items": [{"metadata": {"name": "ws-1"}, "status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}]}))
            elif a[:1] == ["rollout"]: r = ok()
            elif a[:3] == ["patch", "deployment", "workspace"]:
                body = json.loads(a[a.index("-p") + 1])
                for op in body:
                    if op["path"].endswith("/env/-"): live["token"] = True
                    elif op["op"] == "remove": live["token"] = False
                    elif op["path"].endswith("automountServiceAccountToken"): live["automount"] = op["value"]
                r = ok()
            elif a[:2] == ["patch", "resourcequota"]: live["quota"] = json.loads(a[a.index("-p") + 1])["spec"]["hard"]["requests.storage"]; r = ok()
            elif a[:2] == ["create", "role"]: live["role"] = True; r = ok()
            elif a[:2] == ["create", "rolebinding"]: r = ok()
            elif a[:2] == ["delete", "rolebinding,role"]: live["role"] = False; r = ok()
            elif a[:2] == ["delete", "networkpolicy"]: live["nps"].discard(a[2]); r = ok()
            elif a[:2] == ["delete", "pvc"]: r = ok()
            elif a[:3] == ["apply", "-f", "-"]:
                doc = __import__("yaml").safe_load(input)
                if doc["kind"] == "NetworkPolicy": live["nps"].add(doc["metadata"]["name"]); r = ok()
                else: r = ok() if live["quota"] != "1Gi" else (1, "", 'exceeded quota: workspace-bounds, requested: requests.storage=100Ti')
            elif a[:2] == ["auth", "can-i"]:
                rules = "Resources   Non-Resource URLs   Resource Names   Verbs\nselfsubjectreviews.authentication.k8s.io   []   []   [create]\n"
                r = ok(rules + ("pods   []   []   [get list]\n" if live["role"] else ""))
            elif a[:1] == ["exec"]:
                cmd = a[a.index("--") + 1:]; text = " ".join(cmd)
                if "GIT_AUTH_TOKEN" in text: r = (1 if live["token"] else 0, "", "")
                elif "serviceaccount/token" in text: r = (1 if live["automount"] else 0, "", "")
                elif "curl" in cmd[0]:
                    opened = ("denied-fixture" in text and "neg-allow-denied" in live["nps"]) or (":8080" in text and "neg-allow-undeclared" in live["nps"])
                    r = (0, "body", "") if opened else (28, "", "curl: (28) timed out")
                elif "cat > /tmp/ok174-planted-canary" in text: live["planted"] = True; r = ok()
                elif cmd[:2] == ["rm", "-f"]: live["planted"] = False; r = ok()
                elif "grep -a -R" in text: r = (9, "/tmp/ok174-planted-canary:" + canary, "") if live["planted"] else ok()
                else: raise AssertionError(cmd)
            elif a[:2] == ["get", "pvc"]: r = ok(json.dumps({"spec": {"volumeName": "pv-1"}}))
            elif a[:2] == ["get", "pv"] and len(a) > 2 and a[2] == "pv-1": r = ok(json.dumps({"metadata": {"uid": "pv-uid"}}))
            elif a[:3] == ["get", "pv", "-o"]: r = ok(json.dumps({"items": []}))
            elif a[:2] == ["get", "namespace"]:
                found = next((copy.deepcopy(x) for x in expected if x["kind"] == "Namespace" and x["metadata"]["name"] == a[2]), {"metadata": {}})
                found["metadata"]["uid"] = state["namespaceUIDs"][a[2]]
                r = (1, "", "NotFound") if a[2] in live["deleted"] else ok(json.dumps(found))
            elif a[:2] == ["delete", "--raw"]:
                ns = a[2].rsplit("/", 1)[1]; live["deleted"].add(ns); r = ok(json.dumps({"kind": "Namespace", "metadata": {"uid": json.loads(input)["preconditions"]["uid"]}}))
            elif a[:1] == ["get"] and "-n" in a:
                kind = a[1]; items = [proof.normalized(x) for x in expected if x["kind"].lower() == kind]
                if kind == "deployment" and live["token"]: items[0]["spec"]["template"]["spec"]["containers"][0]["env"].append({"name": "GIT_AUTH_TOKEN"})
                r = ok(json.dumps(items[0] if kind == "namespace" else {"items": items}))
            else: raise AssertionError(a)
            return CompletedProcess(args, *r)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); kube = root / "kubeconfig"; kube.write_text("x")
            with patch.dict(os.environ, {"KUBECONFIG": str(kube), "APPROVE_LIVE": "yes", "APPROVE_LIVE_CLEANUP": "yes"}), patch.object(proof, "RAW_DIR", root / "raw"), patch.object(proof, "EVIDENCE_DIR", root), patch.object(proof, "STATE_DIR", root / "state"), patch.object(proof, "NEGATIVE_EVIDENCE", root / "neg.yaml"), patch.object(proof, "git_clean_revision", return_value=state["git"]), patch.object(proof.time, "sleep", lambda _: None):
                doc = proof.negative_controls(proof.Kubectl(run), state)
        controls = {x["name"]: x for x in doc["spec"]["controls"]}
        self.assertEqual(tuple(controls), proof.NEGATIVE_CONTROLS)
        for name, control in controls.items():
            with self.subTest(control=name):
                self.assertEqual((control["status"], control.get("redOnFault"), control.get("greenAfterRevert")), ("PASS", True, True), control.get("error"))
        self.assertEqual(doc["spec"]["status"], "PASS")
        self.assertEqual(live, {"token": False, "automount": False, "role": False, "nps": set(), "quota": "1Gi", "planted": False, "deleted": set(state["namespaceUIDs"])})

    def test_codex_shell_wrapped_verification_counts_but_other_commands_do_not(self):
        def stream(verify_command):
            items = [{"id": "e1", "type": "command_execution", "status": "completed", "exit_code": 0, "aggregated_output": "", "command": "/bin/bash -lc \"printf '%s\\n' 'x' > README.md\""},
                     {"id": "e2", "type": "command_execution", "status": "completed", "exit_code": 0, "aggregated_output": "", "command": verify_command}]
            return "\n".join(json.dumps({"type": "item.completed", "item": x}) for x in items) + "\n" + json.dumps({"type": "turn.completed"})
        self.assertTrue(proof.validate_agent_events("codex", stream("/bin/bash -lc 'sh verify.sh'"), ["sh", "verify.sh"])["editObserved"])
        with self.assertRaises(proof.ProofError): proof.validate_agent_events("codex", stream("/bin/bash -lc 'sh verify.sh || true'"), ["sh", "verify.sh"])

    def test_rbac_accepts_observed_discovery_roles(self):
        observed = "\n".join([
            "Resources                                       Non-Resource URLs                      Resource Names   Verbs",
            "selfsubjectreviews.authentication.k8s.io        []                                     []               [create]",
            "selfsubjectaccessreviews.authorization.k8s.io   []                                     []               [create]",
            "                                                [/.well-known/openid-configuration/]   []               [get]",
            "                                                [/openid/v1/jwks/]                     []               [get]",
            "                                                [/version/]                            []               [get]",
        ])
        self.assertTrue(proof.rbac_list_denied(observed))
        self.assertFalse(proof.rbac_list_denied(observed + "\npods   []   []   [get]"))

    def test_overlay_does_not_leak_run_labels_into_selector(self):
        rendered = proof.rendered_workspace("opencode", "a" * 40)[2]
        objects, _ = proof.overlay(rendered, "r" * 24)
        deployment = next(x for x in objects if x["kind"] == "Deployment")
        self.assertNotIn(proof.RUN_LABEL, deployment["spec"]["selector"]["matchLabels"])
        self.assertIn(proof.RUN_LABEL, deployment["spec"]["template"]["metadata"]["labels"])

    def test_clean_revision_excludes_only_run_outputs(self):
        head = "c" * 40; seen = []
        def runner(args, **_kwargs):
            seen.append(args)
            return CompletedProcess(args, 0, head + "\n" if "rev-parse" in args else dirty, "")
        dirty = ""
        self.assertTrue(proof.git_clean_revision(head, runner)["worktreeClean"])
        status = next(x for x in seen if "status" in x)
        self.assertIn(":(exclude)architecture/spikes/ADR-Platform-039/live/evidence/raw", status)
        self.assertIn(":(exclude)architecture/spikes/ADR-Platform-039/live/evidence/live-evidence-v1.yaml", status)
        dirty = " M architecture/spikes/ADR-Platform-039/live/probes/live_proof.py\n"
        with self.assertRaises(proof.ProofError): proof.git_clean_revision(head, runner)

    def test_log_capture_error_is_not_evidence(self):
        class K:
            def result(self, _args, **_kwargs): return CompletedProcess(["kubectl"], 1, "", "pod has no previous instance")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(proof.ProofError):
                proof.capture_pod_logs(K(), Path(directory), proof.NAMESPACE, "workspace", "opencode")


if __name__ == "__main__":
    unittest.main()
