#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path


class EvaluationError(ValueError):
    pass


REQUIRED = (
    "Status: **Outcome A selected for the tested DEV profile**",
    "Overall OK-141 A/B/C/D:        A",
    "RequiresReconciler:            No",
    "Broad OpenKubes Operator:      Not justified",
    "Persistent Status Adapter:     Not justified by current consumers",
    "ADR-030:                       Proposed; amendment required before acceptance",
    "The management-plane outage scenario remains unexecuted.",
    "No row reached `RequiresReconciler=Proven`.",
)

FORBIDDEN = (
    "ADR-030:                       Accepted",
    "Management outage:             PASS",
    "Public OpenKubes API:          Accepted",
    "Persistent Status Adapter:     Required",
)


def digest(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(path):
    text = Path(path).read_text()
    errors = [f"missing: {value}" for value in REQUIRED if value not in text]
    errors.extend(f"forbidden: {value}" for value in FORBIDDEN if value in text)
    if errors:
        raise EvaluationError("; ".join(errors))
    return text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    verify(args.evaluation)
    print(json.dumps({
        "evaluationDigest": digest(args.evaluation),
        "state": "PASS-FINAL-EVALUATION-OUTCOME-A-ADR-PROPOSED",
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (EvaluationError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
