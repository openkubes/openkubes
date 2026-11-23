#!/usr/bin/env python3
"""Research-only synthetic B-01 declaration assessment; no platform authorization."""
import json
import sys

MAX_BYTES = 8192
SOURCE_REVISION = "42799e8b535d31c1ca1dc07f144fc0f8d124dd93"
SCHEMA = "openkubes.security-assessment.offline-bundle.v0alpha3"
OUTPUT_SCHEMA = "openkubes.security-assessment.offline-result.v0alpha3"


def reject(message):
    # Never include caller-controlled text in errors or output.
    print(json.dumps({"error": message}), file=sys.stderr)
    raise SystemExit(2)


def unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            reject("INVALID_BUNDLE")
        value[key] = item
    return value


def exact(obj, keys):
    if type(obj) is not dict or set(obj) != set(keys):
        reject("INVALID_BUNDLE")


def bounded_text(value, expected):
    if type(value) is not str or value != expected:
        reject("INVALID_BUNDLE")


def assess(data):
    exact(data, ("schema", "fixture_id", "catalog", "control_id", "scope", "completeness", "resources"))
    bounded_text(data["schema"], SCHEMA)
    bounded_text(data["fixture_id"], "synthetic-b01")
    bounded_text(data["control_id"], "B-01")
    exact(data["catalog"], ("version", "source_revision"))
    bounded_text(data["catalog"]["version"], "v0.2")
    bounded_text(data["catalog"]["source_revision"], SOURCE_REVISION)
    exact(data["scope"], ("profile", "namespace"))
    bounded_text(data["scope"]["profile"], "SYNTHETIC_BYOH")
    bounded_text(data["scope"]["namespace"], "fixture-ns")
    exact(data["completeness"], ("grants_complete_for_scope",))
    if data["completeness"]["grants_complete_for_scope"] is not False:
        reject("INVALID_BUNDLE")
    resources = data["resources"]
    if type(resources) is not list or len(resources) != 2:
        reject("INVALID_BUNDLE")
    role, binding = resources
    exact(role, ("kind", "metadata", "rules"))
    bounded_text(role["kind"], "Role")
    exact(role["metadata"], ("name", "namespace"))
    bounded_text(role["metadata"]["name"], "fixture-role")
    bounded_text(role["metadata"]["namespace"], "fixture-ns")
    if type(role["rules"]) is not list or len(role["rules"]) != 1:
        reject("INVALID_BUNDLE")
    rule = role["rules"][0]
    exact(rule, ("apiGroups", "resources", "verbs"))
    for field, value in (("apiGroups", [""]), ("resources", ["secrets"]), ("verbs", ["get"])):
        if type(rule[field]) is not list or rule[field] != value:
            reject("INVALID_BUNDLE")
    exact(binding, ("kind", "metadata", "roleRef", "subjects"))
    bounded_text(binding["kind"], "RoleBinding")
    exact(binding["metadata"], ("name", "namespace"))
    bounded_text(binding["metadata"]["name"], "fixture-binding")
    bounded_text(binding["metadata"]["namespace"], "fixture-ns")
    exact(binding["roleRef"], ("kind", "name"))
    bounded_text(binding["roleRef"]["kind"], "Role")
    bounded_text(binding["roleRef"]["name"], "fixture-role")
    if type(binding["subjects"]) is not list or len(binding["subjects"]) != 1:
        reject("INVALID_BUNDLE")
    exact(binding["subjects"][0], ("kind", "name"))
    bounded_text(binding["subjects"][0]["kind"], "User")
    bounded_text(binding["subjects"][0]["name"], "fixture-host")
    return {
        "schema": OUTPUT_SCHEMA,
        "fixture_id": "synthetic-b01",
        "control_id": "B-01",
        "direct_finding_ids": ["F-01", "F-25"],
        "required_test_ids": ["T-01", "T-02", "T-03", "T-04"],
        "assessment_disposition": "INSUFFICIENT_EVIDENCE",
        "declared_binding_observed": True,
        "source_classification": "UNVERIFIED",
        "verification_disposition": "UNREVIEWED",
        "recorded_platform_test_outcome": "NOT_RUN",
        "current_applicability": "UNKNOWN",
        "profile_approval": "NOT_APPROVED",
        "severity": "UNASSESSED",
        "evidence_gaps": ["Actual-principal live API observations were not supplied"],
    }


def main():
    payload = sys.stdin.buffer.read(MAX_BYTES + 1)
    if not payload or len(payload) > MAX_BYTES:
        reject("INVALID_BUNDLE")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_pairs,
                          parse_constant=lambda _: reject("INVALID_BUNDLE"))
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        reject("INVALID_BUNDLE")
    result = assess(data)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
