"""Private offline source-bound command manifest (not a renderer).

Returns hashes/line counts/source references for one numbered tutorial step.
No command contents are emitted, displayed, modified or executed.
"""
from __future__ import annotations

import hashlib
import re

from docs_mcp import validate_index
from public_beta.source_bound_install_plan import source_bound_install_plan

OPEN = re.compile(r"^ {0,3}(\x60{3,}|~{3,})([a-zA-Z0-9_-]*)[ \t]*$")
SHELL = frozenset({"bash", "sh", "shell", "zsh"})
MAX_STEP_FENCES = 16
MAX_BLOCK_CHARS = 1200


def _source_fences(text: str) -> list[dict]:
    """Find complete exact source fences; never return their contents."""
    lines = text.splitlines(keepends=True)
    results = []
    pos = 0
    while pos < len(lines):
        m = OPEN.fullmatch(lines[pos].rstrip("\r\n"))
        if m is None:
            pos += 1
            continue
        fence, language = m.groups()
        closer = re.compile(r"^ {0,3}" + re.escape(fence[0]) +
                            "{" + str(len(fence)) + r",}[ \t]*$")
        start = pos + 1
        end = start
        while end < len(lines) and not closer.fullmatch(lines[end].rstrip("\r\n")):
            end += 1
        if end == len(lines):
            break
        block = "".join(lines[start:end])
        if (language.lower() in SHELL and block.strip()
                and len(block) <= MAX_BLOCK_CHARS and "\x00" not in block):
            results.append({
                "sha256": hashlib.sha256(block.encode("utf-8")).hexdigest(),
                "line_count": len(block.splitlines()),
                "byte_count": len(block.encode("utf-8")),
                "fence_ordinal": len(results) + 1,
            })
        pos = end + 1
    return results


def source_bound_command_manifest(retrieval: dict, index: dict, *, step: int) -> dict:
    """Return verified source metadata for one step, with no display authority."""
    if type(step) is not int or step not in range(1, 9):
        raise ValueError("Invalid requested step")
    plan = source_bound_install_plan(retrieval, index)
    if plan["status"] != "SOURCE_SEQUENCE_FOUND":
        raise ValueError("Full source-bound sequence required")
    validated = validate_index(index)
    by_id = {item["source_id"]: item for item in validated["corpus"]}
    entries = []
    for sid in plan["steps"][step - 1]["source_ids"]:
        doc = by_id[sid]
        if (doc["repo"] != plan["guide_repo"] or
                doc["path"] != plan["guide_path"] or
                doc["revision"] != plan["revision"]):
            raise ValueError("Source metadata mismatch")
        for fence in _source_fences(doc["text"]):
            if len(entries) >= MAX_STEP_FENCES:
                raise ValueError("Step exceeds manifest command limit")
            entries.append({
                "source_id": sid,
                "revision": doc["revision"],
                **fence,
            })
    return {
        "status": "MANIFEST_ONLY",
        "step": step,
        "guide_repo": plan["guide_repo"],
        "guide_path": plan["guide_path"],
        "revision": plan["revision"],
        "command_block_count": len(entries),
        "blocks": entries,
        "display_authorized": False,
        "execution_authorized": False,
    }
