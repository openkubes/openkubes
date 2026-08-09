import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = HARNESS_DIR / "candidates/argocd-gitops-v1"
SPEC = importlib.util.spec_from_file_location(
    "ok141_harness", HARNESS_DIR / "ok141_harness.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class GitOpsCandidateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(
            (HARNESS_DIR / "fixtures/execution/phase-r-v2.json").read_text()
        )
        self.profile = json.loads(
            (HARNESS_DIR / "profiles/platform/minimal-observability-v2/profile.json").read_text()
        )
        self.applications_path = (
            HARNESS_DIR / "profiles/platform/minimal-observability-v2/applications.yaml"
        )
        self.applications = [
            item
            for item in yaml.safe_load_all(self.applications_path.read_text())
            if item
        ]
        self.root = json.loads((CANDIDATE_DIR / "root-model.json").read_text())
        self.project = yaml.safe_load(
            (CANDIDATE_DIR / "appproject-candidate.yaml").read_text()
        )
        self.registration = yaml.safe_load(
            (CANDIDATE_DIR / "cluster-registration-metadata-candidate.yaml").read_text()
        )
        self.assertion = json.loads(
            (CANDIDATE_DIR / "platformready-assertion.json").read_text()
        )

    def test_direct_application_root_reproduces_frozen_p_prime(self):
        self.assertEqual(self.root["model"], "direct-application")
        self.assertEqual(self.root["requiredApplications"], ["disposable-ok141-observability"])
        self.assertEqual(
            MODULE.validate_platform_applications(self.profile, self.applications),
            self.fixture["platform"]["P"],
        )
        self.assertEqual(self.root["platformRevision"], self.fixture["platform"]["P"])
        self.assertEqual(self.root["executionFixture"], self.fixture["fixtureDigest"])
        self.assertEqual(self.root["authorization"], "NO-GO")

    def test_frozen_application_set_digest_is_unchanged(self):
        self.assertEqual(
            MODULE.semantic_revision(self.applications),
            self.fixture["platform"]["applicationSetDigest"],
        )
        self.assertEqual(
            self.root["applicationSetDigest"],
            self.fixture["platform"]["applicationSetDigest"],
        )

    def test_project_is_narrow_and_deliberately_blocked(self):
        self.assertEqual(
            self.project["metadata"]["annotations"]["openkubes.io/candidate-status"],
            "blocked-no-go",
        )
        self.assertEqual(
            self.project["spec"]["sourceRepos"],
            ["https://github.com/openkubes/ok-observability.git"],
        )
        self.assertEqual(
            self.project["spec"]["destinations"],
            [{"name": "disposable-ok141", "namespace": "observability"}],
        )
        self.assertEqual(self.project["spec"]["clusterResourceWhitelist"], [])
        self.assertNotIn("*", json.dumps(self.project["spec"]))

    def test_registration_is_metadata_only_and_non_operational(self):
        annotations = self.registration["metadata"]["annotations"]
        self.assertEqual(
            self.registration["metadata"]["labels"]["argocd.argoproj.io/secret-type"],
            "cluster",
        )
        self.assertEqual(annotations["openkubes.io/candidate-status"], "blocked-no-go")
        self.assertEqual(self.registration["stringData"]["server"], "https://api.invalid")
        self.assertNotIn("config", self.registration["stringData"])
        for key in (
            "openkubes.io/capi-cluster-uid",
            "openkubes.io/workload-kube-system-uid",
            "openkubes.io/workload-api-ca-sha256",
        ):
            self.assertEqual(annotations[key], "M0B_REQUIRED")

    def test_platformready_requires_immutable_target_and_current_state(self):
        target = self.assertion["targetProof"]
        app = self.assertion["applicationProof"]
        self.assertFalse(target["nameOrServerAloneIsIdentity"])
        self.assertTrue(target["requireExactCAPIClusterUID"])
        self.assertTrue(target["requireLiveKubeSystemNamespaceUID"])
        self.assertTrue(target["requireWorkloadAPICAFingerprint"])
        self.assertEqual(app["requireAppliedRevisionEqualsCommit"], True)
        self.assertEqual(app["requireSyncStatus"], "Synced")
        self.assertEqual(app["requireHealthStatus"], "Healthy")
        self.assertFalse(app["historicalSuccessfulOperationIsCurrentProof"])
        self.assertFalse(
            self.assertion["capabilityProof"]["argoHealthAloneIsCapabilityProof"]
        )
        self.assertEqual(
            set(self.assertion["negativeControls"]),
            {
                "wrong-registration-secret-uid",
                "reused-registration-name",
                "wrong-capi-cluster-uid",
                "wrong-kube-system-uid",
                "wrong-api-ca-fingerprint",
                "mutable-source-revision",
                "missing-required-application",
                "extra-required-application",
                "compared-to-mismatch",
                "historical-success-with-current-error",
                "capability-check-missing-or-stale",
            },
        )
        self.assertEqual(self.assertion["authorization"], "NO-GO")

    def test_pinned_capability_source_exists_when_sibling_is_available(self):
        repository = HARNESS_DIR.parents[3]
        source = repository.parent / "ok-observability"
        if not (source / ".git").is_dir():
            self.skipTest("ok-observability sibling source is not available")
        commit = self.assertion["requiredApplication"]["source"]["commit"]
        subprocess.run(
            ["git", "-C", str(source), "cat-file", "-e", f"{commit}^{{commit}}"],
            check=True,
        )
        path = self.assertion["requiredApplication"]["source"]["path"]
        subprocess.run(
            ["git", "-C", str(source), "cat-file", "-e", f"{commit}:{path}/Chart.yaml"],
            check=True,
        )


if __name__ == "__main__":
    unittest.main()
