"""Offline provenance contract for command-block references; never renders or executes.

References bind to a validated index snapshot, source chunk and fence ordinal.
They do NOT authorize showing the underlying shell text. A separate review and
display gate is required before any user-facing command rendering.
"""
from __future__ import annotations

import hashlib

from docs_mcp import validate_index
from public_beta.source_command_inventory import inventory_shell_blocks

SCHEMA = "source-bound-command-reference/v1"


def build_command_references(index: dict) -> list[dict]:
    """Return provenance-only references for all fully indexed shell fences."""
    corpus = validate_index(index)["corpus"]
    sources = {doc["source_id"]: doc for doc in corpus}
    ordinals: dict[str, int] = {}
    references = []
    for block in inventory_shell_blocks(index):
        sid = block["source_id"]
        doc = sources[sid]
        ordinal = ordinals.get(sid, 0)
        ordinals[sid] = ordinal + 1
        references.append({
            "schema": SCHEMA,
            "source_id": sid,
            "block_ordinal": ordinal,
            "repo": doc["repo"],
            "path": doc["path"],
            "commit_sha": doc["revision"],
            "chunk_sha256": doc["sha256"],
            "block_sha256": block["sha256"],
            "language": block["language"],
            "line_count": block["line_count"],
            "url": block["url"],
            "review": block["review"],
            "display_allowed": False,
        })
    return references


def validate_command_reference(index: dict, reference: dict) -> dict:
    """Fail closed; re-derive exact metadata from the trusted snapshot.

    No command content is returned. Callers must not interpret this validation
    as security approval, publication approval, or execution authorization.
    """
    if not isinstance(reference, dict):
        raise ValueError("Invalid reference")
    if type(reference.get("block_ordinal")) is not int or reference["block_ordinal"] < 0:
        raise ValueError("Invalid block ordinal")
    if reference.get("schema") != SCHEMA or reference.get("display_allowed") is not False:
        raise ValueError("Invalid contract or display gate")
    candidates = [
        item for item in build_command_references(index)
        if item["source_id"] == reference.get("source_id")
        and item["block_ordinal"] == reference["block_ordinal"]
    ]
    if len(candidates) != 1 or reference != candidates[0]:
        raise ValueError("Reference provenance mismatch")
    return candidates[0].copy()
