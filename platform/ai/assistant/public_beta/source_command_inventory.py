"""Offline-only inventory of source code fences, never an execution or rendering gate.

Consumes an already validated, immutable v1 index. Identifies complete
shell fences and classifies them conservatively for manual review.
"""
from __future__ import annotations

import hashlib
import re

from docs_mcp import validate_index

FENCE = re.compile(r"(?m)^(`{3,})(bash|sh)[ \t]*\n([\s\S]*?)^\1[ \t]*$")
SENSITIVE = re.compile(
    r"(?i)(?:\bsudo\b|\bcurl\b|\bwget\b|\bssh\b|\bsecret\b|"
    r"password|token|\binstall\b|\bdelete\b|\bapply\b|"
    r"\breset\b|\blaunch\b|\bexport\b|\bchmod\b|"
    r"\$|[|;&><]|`)"
)
MAX_BLOCKS = 1000


def inventory_shell_blocks(index: dict) -> list[dict]:
    """Metadata only; neither returns commands nor deems a command safe."""
    corpus = validate_index(index)["corpus"]
    output = []
    for doc in corpus:
        text = doc["text"]
        for match in FENCE.finditer(text):
            body = match.group(3)
            if not body or len(body) > 2000 or len(output) >= MAX_BLOCKS:
                raise ValueError("Unsupported command-block inventory")
            output.append({
                "source_id": doc["source_id"],
                "url": doc["url"],
                "language": match.group(2),
                "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                "line_count": len(body.splitlines()),
                "review": "quarantine" if SENSITIVE.search(body) else "manual_review",
            })
        # Conservatively reject malformed or truncated shell fences.
        all_open = len(re.findall(r"(?m)^`{3,}(?:bash|sh)[ \t]*$", text))
        if all_open > len(list(FENCE.finditer(text))):
            raise ValueError("Incomplete shell code fence")
    return output
