#!/usr/bin/env python3
"""Verify the exact, non-executing publisher token-environment amendment."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
WORKFLOW = REPO / ".github/workflows/ok141-evidence-publisher.yaml"
EXPECTED = "sha256:26cd4a5c964159d5920a8bd0b1596ded1d9248e35f752878f409203f23917b7b"


source = WORKFLOW.read_text()
actual = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
if actual != EXPECTED:
    raise SystemExit(f"workflow digest mismatch: {actual}")

final_step = """      - name: Verify pull-back receipt and durable correlation
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
"""
if source.count(final_step) != 1:
    raise SystemExit("final verification token environment is not exact")
if source.count("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}") != 3:
    raise SystemExit("unexpected GH_TOKEN usage count")
if '"on":\n  workflow_dispatch:' not in source or "\n  push:" in source or "\n  pull_request:" in source:
    raise SystemExit("manual-only trigger boundary changed")

print("PASS: exact final-step GH_TOKEN environment; manual-only and not dispatched")
