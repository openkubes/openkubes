#!/usr/bin/env python3
"""Verify exact active-index and credential-free observer deployment source."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
INDEX = ROOT / "active-evidence-index.json"
ACTIVE = REPO / ".github/workflows/ok141-evidence-observer.yaml"
OBSERVER = ROOT.parent / "ghcr-observer-offline-prototype" / "observe_ghcr_evidence.py"
RUNTIME = ROOT / "observe_public_ghcr_evidence_v2.py"
EXPECTED = "sha256:6fed6d68998ce1d79e4465cf8c50ebf264535483e98ea33adca8e89adf06c5c7"
RUNTIME_DIGEST = "sha256:8a9f86981fa9f98389cd16ce30bca70b6b7405bc78866b9ca9b37fafff323f01"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if digest(ACTIVE) != EXPECTED:
    raise SystemExit("active workflow digest mismatch")
if digest(RUNTIME) != RUNTIME_DIGEST:
    raise SystemExit("runtime evaluator digest mismatch")

source = ACTIVE.read_text()
for forbidden in ("packages:", "GHCR_TOKEN", "GITHUB_TOKEN", "secrets.", "kubectl", "kubeconfig"):
    if forbidden in source:
        raise SystemExit(f"forbidden active workflow surface: {forbidden}")

spec = importlib.util.spec_from_file_location("ok141_observer_v1_index", OBSERVER)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)
index = module.load_index(INDEX)
if index["ociManifestDigest"] != "sha256:c9bdeadf1ee859c69ed0ab1136ec6b590139fe931eff44039265c144cea76dc8":
    raise SystemExit("active manifest digest mismatch")
if index["workflowSourceRevision"] != "c177b56a9a925a64f78a56350822e6747a5f169b":
    raise SystemExit("observer source revision mismatch")

print("PASS: exact credential-free observer and active digest index")
