#!/usr/bin/env python3
"""Append one safely encoded, flat observation event to a JSONL stream."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def pairs(values: list[list[str]], label: str) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError(f"duplicate {label} key {key!r}")
        result[key] = value
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--value", nargs=2, action="append", default=[])
    parser.add_argument("--observed", nargs=2, action="append", default=[])
    parser.add_argument("--observed-int", nargs=2, action="append", default=[])
    parser.add_argument("--observed-bool", nargs=2, action="append", default=[])
    args = parser.parse_args()

    stream = Path(args.stream)
    if not stream.is_file():
        raise FileNotFoundError(f"JSONL stream must already exist: {stream}")
    event = {"event": args.event, **pairs(args.value, "value")}
    observed = pairs(args.observed, "observed")
    for key, raw in args.observed_int:
        if key in observed:
            raise ValueError(f"duplicate observed key {key!r}")
        observed[key] = int(raw)
    for key, raw in args.observed_bool:
        if key in observed:
            raise ValueError(f"duplicate observed key {key!r}")
        if raw not in {"true", "false"}:
            raise ValueError(f"observed boolean {key!r} must be true or false")
        observed[key] = raw == "true"
    if not observed:
        raise ValueError("every event must carry observed values")
    event["observed"] = observed
    with stream.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
