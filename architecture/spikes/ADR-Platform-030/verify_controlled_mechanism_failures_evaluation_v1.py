#!/usr/bin/env python3
"""Verify the redacted OK-141 controlled-failure synthesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
EVALUATION = HERE / "controlled-mechanism-failures-evidence-evaluation-v1.md"


class VerificationError(ValueError):
    pass


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def verify(path: Path = EVALUATION) -> str:
    text = path.read_text()
    required = (
        "E1 and P1 execution-proven; overall A/B/C/D remains unclassified",
        "sha256:76513bf068355e3d26db7174ef27633dc6a2c1dd8d476a7b28313fecc99eb655",
        "sha256:3d55cd9eb368302e0116d954da0eb1bd6e2337d90c3ffb3b4508320a6f105369",
        "RequiresReconciler:             none proven",
        "Delete:                       NOT GRANTED",
        "Management outage:            NOT GRANTED",
        "Overall OK-141 A/B/C/D:       unclassified",
        "ADR-030:                       Proposed",
    )
    for value in required:
        if value not in text:
            raise VerificationError(f"missing required claim: {value}")
    forbidden = (
        "BEGIN PRIVATE KEY",
        "client-key-data:",
        "client-certificate-data:",
        "bearerToken:",
        "resourceVersion:",
        "system:masters",
    )
    if any(value in text for value in forbidden):
        raise VerificationError("forbidden payload category")
    return digest(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, default=EVALUATION)
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                {"state": "PASS-REDACTED", "digest": verify(args.evaluation.resolve())},
                sort_keys=True,
            )
        )
        return 0
    except (OSError, VerificationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
