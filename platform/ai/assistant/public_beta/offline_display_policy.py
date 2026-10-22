"""Offline triage policy for *candidate* source-bound shell references.

This does not authorize rendering, copying commands to answers or executing.
Unknown syntax is denied. The underlying inventory and provenance contracts
remain unchanged and always set display_allowed=False.
"""
from __future__ import annotations

import re

from docs_mcp import validate_index
from public_beta.source_bound_command_reference import (
    build_command_references,
    validate_command_reference,
)
from public_beta.source_command_inventory import OPEN

# Explicit whole-line grammar, not a prefix/substring allowlist.
READ_ONLY = (
    re.compile(r"kubectl get nodes(?:\s+--context=[A-Za-z0-9._-]+)?"),
    re.compile(r"kubectl get vm -w"),
    re.compile(r"kubectl get kubevirt kubevirt -n kubevirt\s+-o jsonpath='\{\.spec\.configuration\.developerConfiguration\}'"),
    re.compile(r"clusterctl version"),
    re.compile(r"virtctl version --client"),
)
MAX_BLOCK_LINES = 20


def _shell_bodies(text: str) -> list[str]:
    marker = None
    width = 0
    lang = ""
    body: list[str] = []
    result: list[str] = []
    for line in text.splitlines(keepends=True):
        match = OPEN.match(line.rstrip("\r\n"))
        if marker is None:
            if match:
                marker, width = match.group(1)[0], len(match.group(1))
                lang, body = match.group(2).strip(), []
        elif (match and match.group(1)[0] == marker
              and len(match.group(1)) >= width and not match.group(2).strip()):
            if lang in ("sh", "bash"):
                result.append("".join(body))
            marker, lang, body = None, "", []
        elif lang in ("sh", "bash"):
            body.append(line)
    if marker is not None:
        raise ValueError("Incomplete fence")
    return result


def classify_display_candidate(index: dict, reference: dict) -> dict:
    """Return metadata-only candidate status, never permission to display."""
    canonical = validate_command_reference(index, reference)
    corpus = validate_index(index)["corpus"]
    source = next(d for d in corpus if d["source_id"] == canonical["source_id"])
    bodies = _shell_bodies(source["text"])
    body = bodies[canonical["block_ordinal"]]
    import hashlib
    if hashlib.sha256(body.encode("utf-8")).hexdigest() != canonical["block_sha256"]:
        raise ValueError("Block integrity failure")
    # Each line must be a literal, recognized read-only command or an
    # explanatory comment. No variable expansions, pipelines, redirects,
    # command substitution, shell separators, or wrapper tools are admitted.
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    # Only join a literal backslash-newline in a known kubectl get command.
    # Other continuations remain unrecognized; never evaluate shell syntax.
    normalized = []
    pending = ""
    for line in lines:
        if pending:
            if line.startswith("#") or line.endswith("\\"):
                return _classification(canonical, False)
            line = pending + " " + line
            pending = ""
        if line.endswith("\\"):
            if not line.startswith("kubectl get "):
                return _classification(canonical, False)
            pending = line[:-1].rstrip()
            continue
        normalized.append(line)
    if pending:
        return _classification(canonical, False)

    commands = []
    for line in normalized:
        if line.startswith("#"):
            continue
        # An inline comment is allowed ONLY on an exact version query.
        if line.startswith(("clusterctl version", "virtctl version --client")):
            line = re.sub(r"  +#[^\r\n]*$", "", line)
        commands.append(line)
    allowed = bool(commands) and len(lines) <= MAX_BLOCK_LINES and all(
        any(pattern.fullmatch(line) for pattern in READ_ONLY) for line in commands
    )
    return _classification(canonical, allowed)


def _classification(canonical: dict, allowed: bool) -> dict:
    return {
        "source_id": canonical["source_id"],
        "block_ordinal": canonical["block_ordinal"],
        "block_sha256": canonical["block_sha256"],
        "triage": "low_risk_candidate" if allowed else "needs_manual_review",
        "display_allowed": False,
    }
