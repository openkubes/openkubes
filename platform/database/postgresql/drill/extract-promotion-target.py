#!/usr/bin/env python3
"""Extract the immutable recovery target recorded in PostgreSQL promotion logs."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def main() -> None:
    messages: list[str] = []
    for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            messages.append(raw)
            continue
        record = value.get("record", {})
        messages.append(str(record.get("message", value.get("msg", ""))))

    joined = "\n".join(messages)
    lsn_matches = re.findall(r"redo done at ([0-9A-F]+/[0-9A-F]+)", joined, re.IGNORECASE)
    timeline_matches = re.findall(r"selected new timeline ID:\s*([0-9]+)", joined)
    if "archive recovery complete" not in joined.lower():
        raise ValueError("promotion log lacks archive recovery complete marker")
    if not lsn_matches:
        raise ValueError("promotion log lacks redo-done LSN")
    if not timeline_matches:
        raise ValueError("promotion log lacks selected timeline ID")
    print(f"{timeline_matches[-1]}|{lsn_matches[-1].upper()}")


if __name__ == "__main__":
    main()
