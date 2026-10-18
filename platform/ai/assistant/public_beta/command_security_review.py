"""Offline human-review ledger for pinned tutorial command metadata.

This is NOT an automated safety classifier or an allowlist for rendering.
Reviewer decisions are local annotations, never display/execution permission.
No shell command contents are returned, logged or executed.
"""
from __future__ import annotations

import re

from public_beta.source_bound_command_manifest import source_bound_command_manifest

CATEGORIES = frozenset({
    "required", "optional", "diagnostic", "cleanup", "platform_specific",
    "unsafe_or_unknown",
})
MAX_REVIEW_ROWS = 128
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def command_security_review(retrieval: dict, index: dict, decisions: list | None = None) -> dict:
    """Match manually supplied classifications to exact recomputed source keys.

    Unknown, stale, duplicate or partial-review records are not implicitly
    approved. The output remains a metadata-only report in all cases.
    """
    manifests = [
        source_bound_command_manifest(retrieval, index, step=step)
        for step in range(1, 9)
    ]
    baseline = {}
    for manifest in manifests:
        for block in manifest["blocks"]:
            key = (manifest["step"], block["source_id"], block["fence_ordinal"])
            if key in baseline:
                raise ValueError("Duplicate source block identity")
            baseline[key] = (block["sha256"], block["revision"])
    if len(baseline) > MAX_REVIEW_ROWS:
        raise ValueError("Review exceeds bounded inventory")
    if decisions is None:
        decisions = []
    if not isinstance(decisions, list) or len(decisions) > MAX_REVIEW_ROWS:
        raise ValueError("Invalid review records")
    reviewed = {}
    for record in decisions:
        if not isinstance(record, dict) or set(record) != {
            "step", "source_id", "fence_ordinal", "sha256", "revision", "category"
        }:
            raise ValueError("Invalid review record schema")
        step, sid, ordinal = (record["step"], record["source_id"], record["fence_ordinal"])
        if type(step) is not int or type(ordinal) is not int:
            raise ValueError("Invalid review identity type")
        key = (step, sid, ordinal)
        if key not in baseline or key in reviewed:
            raise ValueError("Stale, unknown or duplicated review identity")
        digest, revision = baseline[key]
        if (not isinstance(record["sha256"], str)
                or not HEX64.fullmatch(record["sha256"])
                or record["sha256"] != digest
                or record["revision"] != revision):
            raise ValueError("Review references stale command or revision")
        if not isinstance(record["category"], str) or record["category"] not in CATEGORIES:
            raise ValueError("Unrecognized review category")
        reviewed[key] = record["category"]

    counts = {category: 0 for category in sorted(CATEGORIES)}
    for category in reviewed.values():
        counts[category] += 1
    pending = len(baseline) - len(reviewed)
    return {
        "status": "REVIEW_INCOMPLETE" if pending else "REVIEW_RECORDED",
        "total_blocks": len(baseline),
        "reviewed_blocks": len(reviewed),
        "pending_blocks": pending,
        "category_counts": counts,
        "review_rows": [
            {
                "step": step,
                "source_id": sid,
                "fence_ordinal": ordinal,
                "sha256": baseline[(step, sid, ordinal)][0],
                "revision": baseline[(step, sid, ordinal)][1],
                "category": reviewed.get((step, sid, ordinal), "pending"),
            }
            for step, sid, ordinal in baseline
        ],
        "display_authorized": False,
        "execution_authorized": False,
        "note": "Human annotations only; a reviewed record never authorizes rendering or execution.",
    }
