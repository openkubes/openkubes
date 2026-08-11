#!/usr/bin/env python3
"""Verify the inert credential-free GHCR observer amendment."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = yaml.safe_load((ROOT / "public-observer-amendment-v1.yaml").read_text())["spec"]


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if SPEC["state"] != "IMPLEMENTED-OFFLINE-INERT-NO-GO":
    raise SystemExit("wrong amendment state")
for name in ("evaluator", "candidateWorkflow"):
    item = SPEC["components"][name]
    if digest(ROOT / item["path"]) != item["digest"]:
        raise SystemExit(f"{name} digest mismatch")

workflow = (ROOT / SPEC["components"]["candidateWorkflow"]["path"]).read_text()
for forbidden in ("packages: write", "packages: read", "GHCR_TOKEN", "GITHUB_TOKEN", "secrets.", "delete", "republish"):
    if forbidden in workflow:
        raise SystemExit(f"forbidden workflow surface: {forbidden}")
if workflow.count("  contents: read\n") != 1:
    raise SystemExit("contents permission is not exact")
if '"on":\n  workflow_dispatch:\n  schedule:' not in workflow:
    raise SystemExit("candidate trigger set mismatch")

contract = SPEC["contract"]
if contract["credentialRequired"] or contract["packageReadPermissionRequired"]:
    raise SystemExit("credential-free boundary changed")
for key in ("packageWritePermissionAllowed", "packageDeletePermissionAllowed", "issueOrWebhookPermissionAllowed"):
    if contract[key]:
        raise SystemExit(f"{key} must remain false")
for key, value in SPEC["authorization"].items():
    if key == "decision":
        if value != "NO-GO":
            raise SystemExit("decision must remain NO-GO")
    elif value:
        raise SystemExit(f"{key} must remain false")

print("PASS: public observer candidate is credential-free, read-only and inert")
