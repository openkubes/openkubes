#!/usr/bin/env python3
# Copyright 2026 The OpenKubes Authors.
# SPDX-License-Identifier: Apache-2.0
"""Tests of hack/check-provider-neutrality.py: python3 -I hack/test-provider-neutrality.py"""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("check", os.path.join(os.path.dirname(__file__), "check-provider-neutrality.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Check(unittest.TestCase):
    def repo(self, files, allowlist="# none\n"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        (root / "hack").mkdir(exist_ok=True)
        (root / "hack/allow.txt").write_text(allowlist)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        return root

    def run_check(self, root):
        return check.scan(root, check.tracked_files(root), check.load_allowlist(root / "hack/allow.txt"))

    def test_detects_provider_references(self):
        for line in ["Runs on Scaleway.", "region fr-par-2", "a DEV1-M instance", "ssh ubuntu@51.158.62.216",
                     "host ok-bm-lab-01", "cluster ok-byoh-scw1", "scw instance list", "an Elastic Metal server",
                     "type EM-A116X", "STARDUST1-S", "server: BunnyCDN", "GP1-XS"]:
            findings, _ = self.run_check(self.repo({"docs/a.md": line + "\n"}))
            self.assertEqual(len(findings), 1, line)

    def test_neutral_text_passes(self):
        findings, stale = self.run_check(self.repo({"docs/a.md": "Bare metal, VMs and clouds. Screw and scwatch.\nip 10.0.0.1\n"}))
        self.assertEqual((findings, stale), ([], []))

    def test_line_marker(self):
        findings, _ = self.run_check(self.repo({"docs/a.md": "[lab](scaleway/x.md) <!-- provider-neutrality: allow (lab record) -->\n"}))
        self.assertEqual(findings, [])

    def test_allowlist_and_stale_entries(self):
        root = self.repo({"docs/lab/a.md": "Scaleway\n"}, "docs/lab/*  # lab records\ndocs/gone/*  # removed\n")
        findings, stale = self.run_check(root)
        self.assertEqual(findings, [])
        self.assertEqual(len(stale), 1)

    def test_allowlist_needs_a_reason(self):
        root = self.repo({"docs/a.md": "x\n"}, "docs/*\n")
        with self.assertRaises(SystemExit):
            check.load_allowlist(root / "hack/allow.txt")


if __name__ == "__main__":
    unittest.main()
