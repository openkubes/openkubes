from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import verify_fresh_run_v2 as verifier


class FreshRunPackageTest(unittest.TestCase):
    def test_package_verifies(self) -> None:
        self.assertTrue(verifier.verify(verifier.generator.HERE).startswith("sha256:"))

    def test_no_go_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in verifier.generator.HERE.iterdir():
                if source.is_file() and source.name != "runner-publication-receipt.json":
                    (root / source.name).write_bytes(source.read_bytes())
            receipt = verifier.generator.HERE / "runner-publication-receipt.json"
            (root / receipt.name).write_bytes(receipt.read_bytes())
            (root / "artifacts").mkdir()
            for source in (verifier.generator.HERE / "artifacts").iterdir():
                (root / "artifacts" / source.name).write_bytes(source.read_bytes())
            plan = json.loads((root / "staged-plan.json").read_text())
            plan["authorizationState"] = "GO"
            (root / "staged-plan.json").write_text(json.dumps(plan))
            with self.assertRaises(verifier.VerificationError):
                verifier.verify(root)


if __name__ == "__main__":
    unittest.main()
