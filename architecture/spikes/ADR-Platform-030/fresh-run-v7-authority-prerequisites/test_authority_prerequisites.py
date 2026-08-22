#!/usr/bin/env python3

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from verify_authority_prerequisites import HERE, verify


class AuthorityPrerequisitesTest(unittest.TestCase):
    def copy(self) -> Path:
        root = Path(tempfile.mkdtemp())
        for name in ("package-manifest.json", "ok-mgmt-authority.yaml", "ok-shared-authority.yaml"):
            shutil.copy2(HERE / name, root / name)
        return root

    def test_package_passes(self):
        self.assertTrue(verify())

    def test_wildcard_fails_closed(self):
        root = self.copy()
        path = root / "ok-shared-authority.yaml"
        docs = list(yaml.safe_load_all(path.read_text()))
        role = next(x for x in docs if x["kind"] == "Role")
        role["rules"][0]["verbs"].append("*")
        path.write_text(yaml.safe_dump_all(docs, sort_keys=False))
        manifest = json.loads((root / "package-manifest.json").read_text())
        import hashlib
        manifest["packages"][path.name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        (root / "package-manifest.json").write_text(json.dumps(manifest))
        self.assertFalse(verify(root))

    def test_missing_exact_name_fails_closed(self):
        root = self.copy()
        path = root / "ok-shared-authority.yaml"
        docs = list(yaml.safe_load_all(path.read_text()))
        policy = next(x for x in docs if x["kind"] == "ValidatingAdmissionPolicy")
        policy["spec"]["validations"][0]["expression"] = policy["spec"]["validations"][0]["expression"].replace(
            "disposable-ok141-observability-dashboards", "foreign-dashboard")
        path.write_text(yaml.safe_dump_all(docs, sort_keys=False))
        manifest = json.loads((root / "package-manifest.json").read_text())
        import hashlib
        manifest["packages"][path.name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        (root / "package-manifest.json").write_text(json.dumps(manifest))
        self.assertFalse(verify(root))

    def test_foreign_plan_fails_closed(self):
        root = self.copy()
        manifest = json.loads((root / "package-manifest.json").read_text())
        manifest["planDigest"] = "sha256:" + "0" * 64
        (root / "package-manifest.json").write_text(json.dumps(manifest))
        self.assertFalse(verify(root))


if __name__ == "__main__":
    unittest.main()
