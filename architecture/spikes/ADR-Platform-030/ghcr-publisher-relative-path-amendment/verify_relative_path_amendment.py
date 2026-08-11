#!/usr/bin/env python3
"""Verify the exact, non-executing OK-141 publisher path amendment."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
WORKFLOW = REPO / ".github/workflows/ok141-evidence-publisher.yaml"
EXPECTED = "sha256:6837271e8929eac133d1f5f6fb1bbaba3b83f61a772f27a856b51e79d673a27b"


source = WORKFLOW.read_text()
actual = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
if actual != EXPECTED:
    raise SystemExit(f"workflow digest mismatch: {actual}")
if source.count('          cd "$RUNNER_TEMP"\n') != 1:
    raise SystemExit("relative working-directory guard is not unique")
if source.count('            "evidence-bundle.tar:application/vnd.openkubes.ok141.evidence.bundle.v1+tar" \\\n') != 1:
    raise SystemExit("relative layer path is not exact")
if '"$RUNNER_TEMP/evidence-bundle.tar:application/vnd.openkubes.ok141.evidence.bundle.v1+tar"' in source:
    raise SystemExit("absolute layer path remains present")
if '"on":\n  workflow_dispatch:' not in source or "\n  push:" in source or "\n  pull_request:" in source:
    raise SystemExit("workflow trigger boundary changed")

print("PASS: exact relative-path publisher amendment; manual-only and not dispatched")
