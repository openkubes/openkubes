from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import verify_fresh_run_v8 as verifier


class FreshRunPackageTest(unittest.TestCase):
    def copy_package(self, root: Path) -> None:
        for source in verifier.generator.HERE.iterdir():
            if source.is_file():
                (root / source.name).write_bytes(source.read_bytes())
        shutil.copytree(verifier.generator.HERE / "artifacts", root / "artifacts")
        shutil.copytree(
            verifier.generator.HERE / "activation-projection",
            root / "activation-projection",
        )

    def test_package_verifies(self) -> None:
        self.assertTrue(verifier.verify(verifier.generator.HERE).startswith("sha256:"))

    def test_no_go_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_package(root)
            plan = json.loads((root / "staged-plan.json").read_text())
            plan["authorizationState"] = "GO"
            (root / "staged-plan.json").write_text(json.dumps(plan))
            with self.assertRaises(verifier.VerificationError):
                verifier.verify(root)

    def test_provider_access_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_package(root)
            policy_path = root / "artifacts/provider-access-policy.json"
            policy = json.loads(policy_path.read_text())
            policy["providerAuthority"] = "another-provider"
            policy_path.write_text(json.dumps(policy))
            with self.assertRaises(verifier.VerificationError):
                verifier.verify(root)

    def test_activation_projection_tamper_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_package(root)
            lifecycle = root / "activation-projection/ok-mgmt-lifecycle.yaml"
            lifecycle.write_bytes(lifecycle.read_bytes() + b"\n# tampered\n")
            with self.assertRaises(verifier.VerificationError):
                verifier.verify(root)


if __name__ == "__main__":
    unittest.main()
