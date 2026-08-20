#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path


class ReadinessError(ValueError):
    pass


REQUIRED = (
    "Status: **BLOCKED / NO-GO / read-only assessment**",
    "Gate A — Safety: BLOCKED",
    "Gate B — Observability: BLOCKED",
    "Gate C — Change Control: BLOCKED",
    "Gate D — Authority: BLOCKED",
    "workers:                    at least 2",
    "Create and independently verify a current ok-mgmt backup",
    "Architecture classification A:       PASS",
    "Management-outage readiness:          BLOCKED",
    "OK-141 Jira completion:                BLOCKED by current acceptance text",
)

FORBIDDEN = (
    "Management-outage readiness:          GO",
    "Infrastructure mutation:              GO",
    "Outage / worker failure:               GO",
    "OK-141 Jira completion:                DONE",
)


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(path):
    text = Path(path).read_text()
    errors = [f"missing: {value}" for value in REQUIRED if value not in text]
    errors.extend(f"forbidden: {value}" for value in FORBIDDEN if value in text)
    if errors:
        raise ReadinessError("; ".join(errors))
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assessment", type=Path, required=True)
    args = parser.parse_args()
    verify(args.assessment)
    print(json.dumps({
        "assessmentDigest": digest(args.assessment),
        "state": "BLOCKED-MANAGEMENT-OUTAGE-NO-GO",
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ReadinessError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
