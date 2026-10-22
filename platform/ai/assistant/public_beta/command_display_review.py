"""Offline review-record contract, NOT an authorization or rendering gate.

Review records are evidence candidates only. This module cannot authenticate
reviewers, attest approvals, grant display rights, or execute commands.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from public_beta.source_bound_command_reference import validate_command_reference

SCHEMA = "command-display-review-record/v1"
DECISIONS = frozenset(("approve_for_review", "reject"))
REVIEWER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{2,127}$")
TICKET = re.compile(r"^OK-[1-9][0-9]{0,8}$")
KEYS = frozenset(("schema", "reference_sha256", "decision", "reviewer",
                  "ticket", "rationale", "reviewed_at", "display_allowed"))


def reference_digest(reference: dict) -> str:
    """Stable fingerprint of a validated reference, never of command content."""
    value = json.dumps(reference, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_review_record(index: dict, reference: dict, *, decision: str,
                      reviewer: str, ticket: str, rationale: str,
                      reviewed_at: str) -> dict:
    """Produce offline review evidence. Caller-supplied identity is not authenticated."""
    canonical = validate_command_reference(index, reference)
    record = {
        "schema": SCHEMA, "reference_sha256": reference_digest(canonical),
        "decision": decision, "reviewer": reviewer, "ticket": ticket,
        "rationale": rationale, "reviewed_at": reviewed_at,
        "display_allowed": False,
    }
    return validate_review_record(index, reference, record)


def validate_review_record(index: dict, reference: dict, record: dict) -> dict:
    """Check strict shape and source binding, without granting trust or display."""
    canonical = validate_command_reference(index, reference)
    if not isinstance(record, dict) or set(record) != KEYS:
        raise ValueError("Invalid review record fields")
    if record["schema"] != SCHEMA or record["display_allowed"] is not False:
        raise ValueError("Unsupported review contract or display request")
    if record["reference_sha256"] != reference_digest(canonical):
        raise ValueError("Review record bound to another source reference")
    if record["decision"] not in DECISIONS:
        raise ValueError("Invalid review decision")
    if not isinstance(record["reviewer"], str) or not REVIEWER.fullmatch(record["reviewer"]):
        raise ValueError("Invalid reviewer identifier")
    if not isinstance(record["ticket"], str) or not TICKET.fullmatch(record["ticket"]):
        raise ValueError("Invalid review ticket")
    rationale = record["rationale"]
    if not isinstance(rationale, str) or not 15 <= len(rationale.strip()) <= 1000:
        raise ValueError("Insufficient review rationale")
    raw = record["reviewed_at"]
    if not isinstance(raw, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", raw):
        raise ValueError("Review timestamp must be UTC RFC3339 seconds")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid review timestamp") from exc
    if not 2020 <= parsed.year <= 2100:
        raise ValueError("Review timestamp outside accepted range")
    return record.copy()
