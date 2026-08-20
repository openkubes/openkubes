#!/usr/bin/env python3
"""Validate that MinIO source and drill policies enforce disjoint authority."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_POLICY = ROOT / "minio-policy-backups-readonly.json"
DRILL_POLICY = ROOT / "minio-policy-drill-write.json"


def actions(policy: dict) -> set[str]:
    result: set[str] = set()
    for statement in policy.get("Statement", []):
        if statement.get("Effect") != "Allow":
            continue
        value = statement.get("Action", [])
        result.update([value] if isinstance(value, str) else value)
    return result


def object_roots(policy: dict) -> set[str]:
    roots: set[str] = set()
    for statement in policy.get("Statement", []):
        value = statement.get("Resource", [])
        resources = [value] if isinstance(value, str) else value
        for resource in resources:
            prefix = "arn:aws:s3:::"
            if resource.startswith(prefix) and "/" in resource[len(prefix):]:
                roots.add(resource[len(prefix):].removesuffix("*"))
    return roots


def paths_overlap(left: str, right: str) -> bool:
    left_fixed = left.split("${", 1)[0].rstrip("/")
    right_fixed = right.split("${", 1)[0].rstrip("/")
    return left_fixed == right_fixed or left_fixed.startswith(right_fixed + "/") or right_fixed.startswith(left_fixed + "/")


def validate(source: dict, drill: dict) -> None:
    for label, policy in (("source", source), ("drill", drill)):
        statements = policy.get("Statement", [])
        assert len(statements) == 3, f"{label} policy must contain exactly three reviewed statements"
        assert all(statement.get("Effect") == "Allow" for statement in statements), (
            f"{label} policy statements must be explicit Allow rules"
        )
        assert all("NotAction" not in statement and "NotResource" not in statement for statement in statements), (
            f"{label} policy must not use NotAction/NotResource"
        )
        location = [
            statement for statement in statements
            if "s3:GetBucketLocation" in (
                [statement.get("Action")] if isinstance(statement.get("Action"), str)
                else statement.get("Action", [])
            )
        ]
        assert len(location) == 1 and "Condition" not in location[0], (
            f"{label} policy must keep GetBucketLocation outside the s3:prefix condition"
        )
    source_actions = actions(source)
    readonly_allowlist = {"s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject"}
    forbidden = sorted(source_actions - readonly_allowlist)
    assert not forbidden, (
        "read-only source policy grants mutation-capable or unreviewed action(s): " + ", ".join(forbidden)
    )
    assert "s3:GetObject" in source_actions, "read-only source policy must grant s3:GetObject"
    assert "s3:PutObject" in actions(drill), "drill policy must grant s3:PutObject"

    source_roots = object_roots(source)
    drill_roots = object_roots(drill)
    assert source_roots, "read-only source policy has no object-scoped resource"
    assert drill_roots, "drill policy has no object-scoped resource"
    overlaps = sorted(
        f"{left!r} overlaps {right!r}"
        for left in source_roots for right in drill_roots if paths_overlap(left, right)
    )
    assert not overlaps, "source and drill write prefixes overlap: " + "; ".join(overlaps)
    assert source_roots == {"ok-db-backups/${aws:username}/"}, source_roots
    assert drill_roots == {"ok-db-drill/${aws:username}/"}, drill_roots


def expect_rejected(label: str, source: dict, drill: dict, text: str) -> None:
    try:
        validate(source, drill)
    except AssertionError as exc:
        message = str(exc)
        assert text in message, f"{label}: rejection was not useful: {message}"
        print(f"NEGATIVE CONTROL PASS: {label}: {message}")
        return
    raise AssertionError(f"negative control was accepted: {label}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    source = json.loads(SOURCE_POLICY.read_text())
    drill = json.loads(DRILL_POLICY.read_text())
    if args.negative_controls:
        mutable_source = copy.deepcopy(source)
        mutable_source["Statement"][1]["Action"].append("s3:Put*")
        expect_rejected("source s3:Put*", mutable_source, drill, "read-only source policy grants mutation")
        deleting_source = copy.deepcopy(source)
        deleting_source["Statement"][1]["Action"].append("s3:Delete*")
        expect_rejected("source s3:Delete*", deleting_source, drill, "read-only source policy grants mutation")
        deny_only_source = copy.deepcopy(source)
        for statement in deny_only_source["Statement"]:
            statement["Effect"] = "Deny"
        expect_rejected("all-Deny source", deny_only_source, drill, "explicit Allow")
        overlapping_drill = copy.deepcopy(drill)
        overlapping_drill["Statement"][1]["Resource"] = "arn:aws:s3:::ok-db-backups/${aws:username}/drill/*"
        expect_rejected("overlapping prefixes", source, overlapping_drill, "prefixes overlap")
        return
    validate(source, drill)
    print("PASS: source is read-only and ok-db-backups/<cluster>/ is disjoint from ok-db-drill/<runid>/")


if __name__ == "__main__":
    main()
