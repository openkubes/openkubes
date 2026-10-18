"""Private offline inventory of original shell fences from same-request docs hits.

Diagnostic ONLY: emits source IDs/counts, never command content; does not grant
display or execution permission. No model text or network calls are involved.
"""
from __future__ import annotations

import re
from docs_mcp import validate_index

OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([a-zA-Z0-9_-]*)[ \t]*$")
ALLOWED = frozenset({"bash", "sh", "shell", "zsh"})
MAX_HITS = 8
MAX_BLOCKS = 16
MAX_BLOCK_CHARS = 1200


def inventory_trusted_fences(retrieval: dict, index: dict) -> dict:
    """Count eligible *complete* source fences with exact hit/index equality."""
    validated = validate_index(index)
    by_id = {doc["source_id"]: doc for doc in validated["corpus"]}
    if not isinstance(retrieval, dict):
        raise ValueError("Invalid retrieval")
    hits = retrieval.get("results")
    if not isinstance(hits, list) or not 1 <= len(hits) <= MAX_HITS:
        raise ValueError("Invalid retrieval count")
    seen = set()
    entries = []
    total = 0
    for hit in hits:
        if not isinstance(hit, dict):
            raise ValueError("Invalid hit")
        sid = hit.get("source_id")
        doc = by_id.get(sid)
        if doc is None or sid in seen:
            raise ValueError("Unknown or duplicate source")
        seen.add(sid)
        for key, expected in (
            ("snippet", doc["text"]), ("url", doc["url"]),
            ("repo", doc["repo"]), ("path", doc["path"]),
            ("commit_sha", doc["revision"]), ("title", doc["section"])
        ):
            if hit.get(key) != expected:
                raise ValueError("Retrieved hit does not match pinned index")
        lines = doc["text"].splitlines(keepends=True)
        pos = 0
        count = 0
        while pos < len(lines):
            opening = OPEN.fullmatch(lines[pos].rstrip("\r\n"))
            if opening is None:
                pos += 1
                continue
            fence, lang = opening.groups()
            closer = re.compile(r"^ {0,3}" + re.escape(fence[0]) +
                                "{" + str(len(fence)) + r",}[ \t]*$")
            start = pos + 1
            end = start
            while end < len(lines) and not closer.fullmatch(lines[end].rstrip("\r\n")):
                end += 1
            if end >= len(lines):
                break
            block = "".join(lines[start:end])
            if (lang.lower() in ALLOWED and block.strip()
                    and len(block) <= MAX_BLOCK_CHARS
                    and "\x00" not in block):
                count += 1
                total += 1
                if total > MAX_BLOCKS:
                    raise ValueError("Too many command fences")
            pos = end + 1
        entries.append({"source_id": sid, "eligible_shell_fences": count})
    return {
        "status": "INVENTORY_ONLY",
        "retrieved_sources": len(hits),
        "eligible_shell_fences": total,
        "sources": entries,
        "display_authorized": False,
        "execution_authorized": False,
    }
