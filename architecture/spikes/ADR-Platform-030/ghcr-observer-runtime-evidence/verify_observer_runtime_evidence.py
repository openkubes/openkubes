#!/usr/bin/env python3
"""Verify the redacted first live observer evidence."""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent
SPEC = yaml.safe_load((ROOT / "observer-runtime-evidence-v1.yaml").read_text())["spec"]
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


if SPEC["state"] != "FIRST-LIVE-OBSERVATION-VERIFIED-NO-GO":
    raise SystemExit("wrong runtime evidence state")
if SPEC["run"]["id"] != 31519905262 or SPEC["run"]["conclusion"] != "success":
    raise SystemExit("wrong run outcome")
if SPEC["observation"]["status"] != "OBSERVED-PRESENT" or SPEC["observation"]["reason"] != "ExactDigestPresent":
    raise SystemExit("wrong observation outcome")
for field in ("ociManifestDigest", "internalBundleDigest"):
    if DIGEST.fullmatch(SPEC["observation"][field]) is None:
        raise SystemExit(f"invalid {field}")
if SPEC["deployment"]["permissions"] != {"contents": "read"}:
    raise SystemExit("workflow permission boundary mismatch")
for key in (
    "registryCredentialUsed",
    "packageReadPermissionUsed",
    "packageWritePermissionUsed",
    "packageDeletePermissionUsed",
    "clusterAccess",
    "infrastructureMutation",
    "scheduledRunDeliveryGuaranteed",
    "alertNotificationGuaranteed",
):
    if SPEC["boundaries"][key] is not False:
        raise SystemExit(f"{key} must remain false")
if SPEC["outcome"]["go1Granted"] or SPEC["outcome"]["failureInjectionAuthorized"]:
    raise SystemExit("GO-1 and failure injection must remain false")

print("PASS: first public observer run is exact, credential-free and non-authorizing")
