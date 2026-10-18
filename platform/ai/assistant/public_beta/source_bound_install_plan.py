"""Offline source-bound *inventory* of a pinned installation tutorial.

This is not an executable plan or command renderer. It recognizes the
reviewed ok-local beginner guide, verifies same-request retrieval anchors,
and inventories ordered source sections from the SAME validated index.
No network, model-generated paths, command output, or execution.
"""
from __future__ import annotations

import re

from docs_mcp import validate_index

GUIDE_REPO = "openkubes/ok-local"
GUIDE_PATH = "docs/tutorial-basic.md"
EXPECTED_STEPS = tuple(range(1, 9))
STEP = re.compile(r"^Step ([1-9][0-9]*)\s*[—–-]\s*\S", re.I)
MAX_GUIDE_CHUNKS = 64
MAX_ANCHOR_HITS = 8


def source_bound_install_plan(retrieval: dict, index: dict) -> dict:
    """Return metadata-only step inventory, never executable instructions.

    The caller must pass the exact same-request hits and pinned index. The
    result is a diagnostic: even a full eight-step inventory does not attest
    command safety, platform suitability, or end-to-end documentation validity.
    """
    corpus = validate_index(index)["corpus"]
    by_id = {doc["source_id"]: doc for doc in corpus}
    if not isinstance(retrieval, dict):
        raise ValueError("Invalid retrieval")
    hits = retrieval.get("results")
    if not isinstance(hits, list) or not 1 <= len(hits) <= MAX_ANCHOR_HITS:
        raise ValueError("Invalid retrieval hits")

    anchors = []
    seen = set()
    for hit in hits:
        if not isinstance(hit, dict):
            raise ValueError("Invalid retrieval hit")
        sid = hit.get("source_id")
        doc = by_id.get(sid)
        if doc is None or sid in seen:
            raise ValueError("Unknown or duplicate retrieval source")
        seen.add(sid)
        for key, value in (
            ("snippet", doc["text"]), ("repo", doc["repo"]),
            ("path", doc["path"]), ("commit_sha", doc["revision"]),
            ("url", doc["url"]), ("title", doc["section"]),
        ):
            if hit.get(key) != value:
                raise ValueError("Retrieval does not match pinned index")
        if doc["repo"] == GUIDE_REPO and doc["path"] == GUIDE_PATH:
            anchors.append(doc)

    if not anchors:
        return _result("NO_GUIDE_ANCHOR", [], (), None)

    revisions = {doc["revision"] for doc in anchors}
    if len(revisions) != 1:
        raise ValueError("Mixed revisions in guide retrieval")
    revision = next(iter(revisions))
    guide = [doc for doc in corpus
             if doc["repo"] == GUIDE_REPO and doc["path"] == GUIDE_PATH]
    if len(guide) > MAX_GUIDE_CHUNKS:
        raise ValueError("Guide exceeds bounded inventory")
    if any(doc["revision"] != revision for doc in guide):
        raise ValueError("Mixed guide revisions in pinned index")

    # Index order is Markdown source order. Do NOT use lexical hit ranking or
    # model-selected source IDs to rearrange the installation sequence.
    found = {}
    step_numbers = []
    last = None
    for doc in guide:
        match = STEP.match(doc["section"])
        if match is None:
            continue
        n = int(match.group(1))
        if n not in EXPECTED_STEPS:
            continue
        if last is not None and n < last:
            raise ValueError("Guide steps out of source order")
        if n != last:
            step_numbers.append(n)
            found[n] = []
        found[n].append(doc["source_id"])
        last = n
    complete = step_numbers == list(EXPECTED_STEPS)
    steps = [
        {"step": n, "source_ids": found.get(n, [])}
        for n in EXPECTED_STEPS
    ]
    return _result("SOURCE_SEQUENCE_FOUND" if complete else "INCOMPLETE_SEQUENCE",
                   steps, tuple(step_numbers), revision)


def _result(status: str, steps: list, present: tuple, revision: str | None) -> dict:
    return {
        "status": status,
        "guide_repo": GUIDE_REPO,
        "guide_path": GUIDE_PATH,
        "revision": revision,
        "expected_steps": list(EXPECTED_STEPS),
        "present_steps": list(present),
        "steps": steps,
        "display_authorized": False,
        "execution_authorized": False,
        "note": "Metadata-only index sequence; not proof of safety or installation completeness.",
    }
