"""Offline-only inventory of source code fences, never an execution or rendering gate.

Consumes an already validated, immutable v1 index. Identifies complete
shell fences and classifies them conservatively for manual review.
"""
from __future__ import annotations

import hashlib
import re

from docs_mcp import validate_index

OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})([^\r\n]*)$")
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
        # Parse fences sequentially, matching the indexer's fence grammar.
        # Never pair an opening shell fence with a later unrelated closing one.
        fence_char = ""
        fence_width = 0
        shell = False
        language = ""
        body_lines = []
        for line in doc["text"].splitlines(keepends=True):
            match = OPEN.match(line.rstrip("\\r\\n"))
            if not fence_char:
                if match:
                    fence_char = match.group(1)[0]
                    fence_width = len(match.group(1))
                    info = match.group(2).strip()
                    shell = info in ("bash", "sh")
                    language = info
                    body_lines = []
                continue
            if match and match.group(1)[0] == fence_char and len(match.group(1)) >= fence_width and not match.group(2).strip():
                if shell:
                    body = "".join(body_lines)
                    if not body or len(body) > 2000 or len(output) >= MAX_BLOCKS:
                        raise ValueError("Unsupported command-block inventory")
                    output.append({
                        "source_id": doc["source_id"],
                        "url": doc["url"],
                        "language": language,
                        "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                        "line_count": len(body.splitlines()),
                        "review": "quarantine" if SENSITIVE.search(body) else "manual_review",
                    })
                fence_char = ""
                shell = False
            elif shell:
                body_lines.append(line)
        if fence_char:
            raise ValueError("Incomplete fenced code block")
    return output
