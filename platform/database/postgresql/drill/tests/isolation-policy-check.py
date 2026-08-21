#!/usr/bin/env python3
"""Validate that MinIO source and drill policies enforce disjoint authority."""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_POLICY = ROOT / "minio-policy-backups-readonly.json"
DRILL_POLICY = ROOT / "minio-policy-drill-write.json"


# Finding 3: these denial renderings were MEASURED against this exact mc build, and nothing
# otherwise ties the two together. mc renders a 403 as "Insufficient permissions to access this
# path" and never prints "AccessDenied"; boto3/aws-cli do surface the code, so both forms are
# accepted. If the client is bumped without re-measuring, an unrecognised denial falls through to
# "inconclusive" — which silently converts a real permission denial into no result at all.
DENIAL_STRINGS_VALIDATED_AGAINST = (
    "quay.io/minio/mc:RELEASE.2025-08-13T08-35-41Z"
    "@sha256:eb4ea9884b77704230e2423e9004d2fa738dc272876b9cc41a297d29443b8780"
)
ACCEPTED_DENIAL_STRINGS = ("AccessDenied", "Insufficient permissions", "Access Denied")
DRILL_SCRIPT = ROOT / "run-restore-drill.sh"


def check_denial_string_pinning() -> None:
    """The accepted denial strings must stay paired with the client they were measured against."""
    script = DRILL_SCRIPT.read_text()
    images = set(re.findall(r"quay\.io/minio/mc:[A-Za-z0-9.\-]+@sha256:[a-f0-9]{64}", script))
    for provisioner in ("provision-minio.sh", "provision-drill-writer.sh"):
        images |= set(
            re.findall(
                r"quay\.io/minio/mc:[A-Za-z0-9.\-]+@sha256:[a-f0-9]{64}",
                (ROOT / provisioner).read_text(),
            )
        )
    assert images, "no pinned mc image found; the denial strings have nothing to be paired with"
    unexpected = sorted(i for i in images if i != DENIAL_STRINGS_VALIDATED_AGAINST)
    assert not unexpected, (
        "the pinned mc client changed but the accepted denial strings were not re-measured "
        f"against it: {unexpected}. Re-run the write-denial probe, confirm what the new client "
        "actually prints, then update DENIAL_STRINGS_VALIDATED_AGAINST"
    )
    # The drill has TWO denial `case` blocks: an inconclusive-causes filter first, then the
    # acceptance test. Slicing across both let a string removed from the ACCEPTANCE block still
    # be "found" in the span, so this locates the acceptance block specifically — the one whose
    # `*)` arm exits non-zero.
    acceptance = None
    for block in script.split('case "' + chr(92) + '$denial" in')[1:]:
        body = block[: block.index("esac")]
        if "without an authenticated permission denial" in body:
            acceptance = body
            break
    assert acceptance is not None, (
        "could not locate the drill's denial ACCEPTANCE block; the probe structure changed and "
        "this pairing check needs revisiting rather than deleting"
    )
    missing = [needle for needle in ACCEPTED_DENIAL_STRINGS if needle not in acceptance]
    assert not missing, (
        f"the drill's acceptance block no longer accepts denial rendering(s) {missing}. An "
        "unrecognised denial exits as 'not a permission denial', so dropping the rendering the "
        "pinned client actually prints would turn every real refusal into a probe failure"
    )
    print(
        "PASS: denial strings are paired with the mc build they were measured against "
        f"({DENIAL_STRINGS_VALIDATED_AGAINST.split('@')[0].split(':')[-1]})"
    )


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
    # §13 finding 4. Name enumeration is NOT confinable by policy here: Barman's HeadBucket needs
    # bucket-level s3:ListBucket with no s3:prefix condition (asserted in
    # minio-provisioning-check.py), so every identity holding the source policy can enumerate
    # every object NAME in that bucket. Prefix isolation confines s3:GetObject only.
    #
    # Two consequences, and both are asserted rather than described. A Sid must not claim the
    # listing is prefix-scoped, because all three policies shipped saying exactly that. And the
    # separate-bucket precondition is the real isolation boundary for names: the drill must write
    # to a DIFFERENT bucket, not merely a different prefix, or the drill identity could enumerate
    # the production backup namespace.
    for label, policy in (("source", source), ("drill", drill)):
        for statement in policy.get("Statement", []):
            acts = statement.get("Action")
            acts = [acts] if isinstance(acts, str) else (acts or [])
            if "s3:ListBucket" not in acts:
                continue
            sid = statement.get("Sid", "")
            assert not ("ListOnly" in sid and "Prefix" in sid), (
                f"{label} policy Sid {sid!r} claims prefix-scoped listing, but this grant is "
                "bucket-wide by necessity — the Sid must not describe an isolation it does not "
                "provide"
            )

    def bucket_of(policy):
        for statement in policy.get("Statement", []):
            resource = statement.get("Resource", "")
            if isinstance(resource, str) and resource.startswith("arn:aws:s3:::"):
                return resource[len("arn:aws:s3:::"):].split("/", 1)[0]
        return None

    source_bucket, drill_bucket = bucket_of(source), bucket_of(drill)
    assert source_bucket and drill_bucket, "could not determine both bucket names"
    assert source_bucket != drill_bucket, (
        f"the drill writes into the source bucket {source_bucket!r}. Since bucket-wide listing "
        "cannot be withheld, a shared bucket lets the drill identity enumerate the production "
        "backup namespace — a SEPARATE BUCKET is the precondition for name isolation, not a "
        "separate prefix"
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
    check_denial_string_pinning()
    print("PASS: source is read-only and ok-db-backups/<cluster>/ is disjoint from ok-db-drill/<runid>/")


if __name__ == "__main__":
    main()
