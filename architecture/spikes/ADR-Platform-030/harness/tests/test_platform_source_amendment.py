import copy
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path

import yaml


HARNESS_DIR = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HARNESS_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLATFORM = load_module("ok141_platform_source_amendment_test", "ok141_platform_source_amendment.py")
PHASE = load_module("ok141_phase_r_v4_test", "ok141_phase_r_v4.py")


class PlatformSourceAmendmentTests(unittest.TestCase):
    def setUp(self):
        profile_dir = HARNESS_DIR / "profiles/platform/minimal-observability-v4"
        self.profile = json.loads((profile_dir / "profile.json").read_text())
        self.apps = [item for item in yaml.safe_load_all((profile_dir / "applications.yaml").read_text()) if item]
        self.values = PLATFORM.V1.read_yaml_or_json(profile_dir / "provider-values.yaml")
        self.fixture = json.loads((HARNESS_DIR / "fixtures/execution/phase-r-v4.json").read_text())

    def validate(self, profile=None, apps=None):
        return PLATFORM.validate_platform_source_amendment(
            profile if profile is not None else self.profile,
            apps if apps is not None else self.apps,
            self.values,
        )

    def test_authoritative_source_closure_reproduces_p_triple_prime(self):
        self.assertEqual(self.validate(), self.fixture["platform"]["P"])

    def test_old_or_mutable_source_revision_fails_closed(self):
        for revision in (PLATFORM.OLD_COMMIT, "main"):
            changed = copy.deepcopy(self.apps)
            changed[0]["spec"]["source"]["targetRevision"] = revision
            with self.assertRaises(PLATFORM.V1.HarnessError):
                self.validate(apps=changed)

    def test_missing_or_tampered_package_closure_fails_closed(self):
        missing = copy.deepcopy(self.profile)
        missing["requiredApplications"][0]["sourceArtifacts"].pop("sourceClosure")
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(profile=missing)
        changed = copy.deepcopy(self.profile)
        changed["requiredApplications"][0]["sourceArtifacts"]["sourceClosure"]["packages"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(PLATFORM.V1.HarnessError):
            self.validate(profile=changed)

    def test_authoritative_commit_contains_every_bound_artifact(self):
        source = HARNESS_DIR.parents[3].parent / "ok-observability"
        if not (source / ".git").is_dir():
            self.skipTest("ok-observability sibling source is not available")
        core = self.profile["requiredApplications"][0]
        closure = core["sourceArtifacts"]["sourceClosure"]
        artifacts = [closure["artifactLock"], *closure["packages"]]
        for artifact in artifacts:
            raw = subprocess.run(
                ["git", "-C", str(source), "show", f"{PLATFORM.COMMIT}:{artifact['path']}"],
                check=True,
                capture_output=True,
            ).stdout
            self.assertEqual(PLATFORM.V1.sha256_bytes(raw), artifact["digest"])
        lock_raw = subprocess.run(
            ["git", "-C", str(source), "show", f"{PLATFORM.COMMIT}:{closure['artifactLock']['path']}"],
            check=True,
            capture_output=True,
        ).stdout
        lock = json.loads(lock_raw)
        self.assertEqual(lock["schema"], PLATFORM.LOCK_SCHEMA)
        self.assertEqual(
            {item["path"].split("charts/", 1)[-1]: "sha256:" + item["sha256"] for item in lock["packages"]},
            {path.split("charts/", 1)[-1]: digest for path, digest in PLATFORM.PACKAGES.items()},
        )

    def test_phase_r_v4_reproduces_and_v3_remains_historical(self):
        self.assertEqual(PHASE.validate(self.fixture, HARNESS_DIR), self.fixture["fixtureDigest"])
        v3 = json.loads((HARNESS_DIR / "fixtures/execution/phase-r-v3.json").read_text())
        self.assertEqual(PHASE.V3.validate(v3, HARNESS_DIR), v3["fixtureDigest"])
        self.assertEqual(self.fixture["supersedes"]["fixtureDigest"], v3["fixtureDigest"])


if __name__ == "__main__":
    unittest.main()
