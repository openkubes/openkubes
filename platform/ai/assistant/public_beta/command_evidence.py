"""Private-only structural shell evidence report, never an acceptance gate.

No command text, URLs, snippets or hashes are serialized. Whitespace-only
matches are diagnostic and MUST NOT be accepted by answer_integrity.
"""
from __future__ import annotations

import re

from answer_integrity import FENCE
from docs_mcp import validate_index


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _match(block: str, passages: list[str], *, relaxed: bool = False) -> bool:
    if relaxed:
        candidate = _normalized(block)
        return bool(candidate) and any(candidate in _normalized(p) for p in passages)
    return bool(block.strip()) and any(block in p for p in passages)


def _line_evidence(block: str, selected: list[str], remaining: list[str]) -> dict:
    """Classify nonblank lines only, without claiming they are safe commands."""
    selected_lines = {line.strip() for passage in selected
                      for line in passage.splitlines() if line.strip()}
    remaining_lines = {line.strip() for passage in remaining
                       for line in passage.splitlines() if line.strip()}
    selected_relaxed = {_normalized(line) for line in selected_lines}
    remaining_relaxed = {_normalized(line) for line in remaining_lines}
    counts = {
        "exact_retrieved": 0,
        "exact_other_index": 0,
        "whitespace_only_retrieved": 0,
        "whitespace_only_other_index": 0,
        "not_found_in_index": 0,
    }
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Whole line equality only: no substring/token matching.
        if stripped in selected_lines:
            category = "exact_retrieved"
        elif stripped in remaining_lines:
            category = "exact_other_index"
        elif _normalized(stripped) in selected_relaxed:
            category = "whitespace_only_retrieved"
        elif _normalized(stripped) in remaining_relaxed:
            category = "whitespace_only_other_index"
        else:
            category = "not_found_in_index"
        counts[category] += 1
    return counts


def command_evidence_report(answer: str, retrieval: dict, index: dict) -> dict:
    if not isinstance(answer, str) or not isinstance(retrieval, dict):
        raise ValueError("Invalid diagnostic inputs")
    corpus = validate_index(index)["corpus"]
    by_id = {doc["source_id"]: doc for doc in corpus}
    hits = retrieval.get("results")
    if not isinstance(hits, list) or not 1 <= len(hits) <= 8:
        raise ValueError("Invalid hits")
    retrieved_ids = set()
    for hit in hits:
        if not isinstance(hit, dict):
            raise ValueError("Invalid hit")
        doc = by_id.get(hit.get("source_id"))
        if doc is None or any(hit.get(key) != expected for key, expected in (
            ("snippet", doc["text"]), ("url", doc["url"]),
            ("path", doc["path"]), ("repo", doc["repo"]),
            ("title", doc["section"]), ("commit_sha", doc["revision"]),
        )):
            raise ValueError("Retrieval mismatches validated index")
        retrieved_ids.add(doc["source_id"])

    selected = [doc["text"].replace("\r\n", "\n") for doc in corpus
                if doc["source_id"] in retrieved_ids]
    remaining = [doc["text"].replace("\r\n", "\n") for doc in corpus
                 if doc["source_id"] not in retrieved_ids]
    entries = []
    for n, match in enumerate(FENCE.finditer(answer), start=1):
        block = match.group(1).replace("\r\n", "\n")
        if _match(block, selected):
            status = "exact_retrieved"
        elif _match(block, remaining):
            status = "exact_other_index"
        elif _match(block, selected, relaxed=True):
            status = "whitespace_only_retrieved"
        elif _match(block, remaining, relaxed=True):
            status = "whitespace_only_other_index"
        else:
            status = "not_found_in_index"
        # Fixed strings/counts only; these fields never echo model input.
        entries.append({
            "ordinal": n,
            "evidence": status,
            "line_count": len(block.splitlines()),
            "nonempty_line_count": sum(bool(line.strip()) for line in block.splitlines()),
            "line_evidence_counts": _line_evidence(block, selected, remaining),
        })
    return {
        "recognized_shell_blocks": len(entries),
        "blocks": entries,
        "note": "Diagnostic only; matching individual lines does not validate a whole command block.",
    }
