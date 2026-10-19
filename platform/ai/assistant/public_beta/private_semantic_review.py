"""Explicit opt-in PRIVATE human semantic review capture, never public routing.

Writes a local review packet ONLY for a structurally accepted model answer.
No raw rejected response, credentials, or private network endpoint in output.
This does NOT establish semantic grounding or attest model context use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from docs_mcp import DocsRetriever, load_index
from public_beta.gateway_context import build_context_envelope, encode_context_envelope
from public_beta.private_context_gateway_probe import send_private_context
from public_beta.structured_answer import ContractRejected, validate_and_render

CATALOG = Path(__file__).with_name("golden_eval_cases.json")
MAX_REVIEW_BYTES = 80_000


def _write_private_new_file(destination: Path, data: bytes) -> None:
    """Exclusive file creation, mode 0600; never follow a pre-existing link."""
    if len(data) > MAX_REVIEW_BYTES:
        raise ValueError("review_packet_too_large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def capture_private_review(index: dict, case_id: str, output_dir: Path,
                           *, send=None) -> dict:
    """One golden case, exactly one same-request trusted retrieval + A2A send.

    Only structurally accepted answers reach disk, and only at an existing,
    user-owned, private directory. No auto-approve flags or batch execution.
    Return metadata suitable for stdout, never question, snippets or answer.
    """
    spec = json.loads(CATALOG.read_text(encoding="utf-8"))
    matches = [c for c in spec["cases"] if c["id"] == case_id]
    if len(matches) != 1:
        raise ValueError("unknown_review_case")
    if not isinstance(output_dir, Path) or not output_dir.is_dir():
        raise ValueError("review_dir_missing")
    if output_dir.is_symlink():
        raise ValueError("review_dir_symlink")
    stat = output_dir.stat()
    if stat.st_mode & 0o077 or stat.st_uid != os.getuid():
        raise ValueError("review_dir_not_private")
    question = matches[0]["question"]
    hits = DocsRetriever(index).docs_search(question, limit=8)
    if not hits["results"]:
        return {"status": "NO_SOURCES", "case_id": case_id,
                "semantic_grounding": "UNVERIFIED"}
    context = build_context_envelope(question, hits, index)
    raw = (send or send_private_context)(encode_context_envelope(context))
    try:
        rendered = validate_and_render(raw, hits, index)
    except (ContractRejected, ValueError, TypeError, KeyError):
        return {"status": "REJECT", "case_id": case_id,
                "semantic_grounding": "UNVERIFIED"}
    source_ids = set()
    payload = json.loads(raw)
    for step in payload["steps"]:
        source_ids.update(step["source_ids"])
    by_id = {item["source_id"]: item for item in hits["results"]}
    # Review material is deliberately sensitive: use only on a private machine.
    packet = {
        "version": "0.1",
        "case_id": case_id,
        "question": question,
        "kind": matches[0]["kind"],
        "review_rubric": matches[0]["human_review"],
        "accepted_structurally": True,
        "semantic_grounding": "UNVERIFIED",
        "context_sha256": context["context_sha256"],
        "index_sha256": context["payload"]["index_sha256"],
        "rendered_answer": rendered,
        "sources_used": [
            {"source_id": sid, "repo": by_id[sid]["repo"],
             "path": by_id[sid]["path"],
             "commit_sha": by_id[sid]["commit_sha"],
             "url": by_id[sid]["url"],
             "exact_retrieved_snippet": by_id[sid]["snippet"]}
            for sid in sorted(source_ids)
        ],
        "review_decision": "PENDING_HUMAN_REVIEW",
    }
    data = (json.dumps(packet, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    filename = f"{case_id}-{context['context_sha256'][:12]}.json"
    _write_private_new_file(output_dir / filename, data)
    return {"status": "CAPTURED_PRIVATE", "case_id": case_id,
            "source_count": len(source_ids), "answer_chars": len(rendered),
            "semantic_grounding": "UNVERIFIED"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", required=True,
                        help="Preexisting owner-owned directory mode 0700")
    parser.add_argument("--ack-private-review", action="store_true",
                        help="Explicit consent to store an accepted answer and snippets locally")
    args = parser.parse_args()
    if not args.ack_private_review:
        raise SystemExit("STOP: --ack-private-review required")
    try:
        result = capture_private_review(
            load_index(args.index), args.case_id, Path(args.output_dir))
    except Exception:
        # Never reflect paths, arbitrary errors or sensitive model content.
        result = {"status": "ERROR", "reason": "private_review_failed",
                  "semantic_grounding": "UNVERIFIED"}
    print(json.dumps(result, sort_keys=True))
    if result["status"] != "CAPTURED_PRIVATE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
