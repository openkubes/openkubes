import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


GEN = load("ok141_capability_boundary_generator_test", HERE / "generate_capability_name_boundary_amendment_v1.py")


class CapabilityNameBoundaryAmendmentTests(unittest.TestCase):
    def test_offline_verifier_passes(self):
        result = subprocess.run(
            ["python3", str(HERE / "verify_capability_name_boundary_amendment_v1.py")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "PASS")

    def test_authoritative_source_artifacts_match(self):
        self.assertEqual(
            GEN.V1.sha256_bytes(GEN.git_bytes(GEN.NEW_COMMIT, "tests/contract-test.sh")),
            GEN.NEW_SCRIPT_DIGEST,
        )
        self.assertEqual(
            GEN.V1.sha256_bytes(GEN.git_bytes(GEN.NEW_COMMIT, "profiles/ok-observability-standard/artifact-lock.json")),
            GEN.NEW_LOCK_DIGEST,
        )

    def test_name_algorithm_is_bounded_for_historical_and_long_run_ids(self):
        for run_id in ("ok141-capability-runtime-20260815-v1", "x" * 200):
            slug = "".join(character if character.isalnum() else "-" for character in run_id)
            checksum = subprocess.run(
                ["cksum"], input=run_id.encode(), check=True, capture_output=True
            ).stdout.decode().split()[0]
            run_label = f"{slug[:46]}-{checksum}"
            self.assertLessEqual(len(run_label), 57)
            self.assertLessEqual(len("oo-ct-" + run_label), 63)
            self.assertLessEqual(len("oo-log-" + run_label), 63)

    def test_v8_remains_reproducible(self):
        amendment = json.loads((HERE / "capability-name-boundary-amendment-v1.json").read_text())
        old_profile = json.loads((GEN.V8_PROFILE / "profile.json").read_text())
        self.assertEqual(GEN.V1.semantic_revision(old_profile), amendment["spec"]["base"]["P"])


if __name__ == "__main__":
    unittest.main()
