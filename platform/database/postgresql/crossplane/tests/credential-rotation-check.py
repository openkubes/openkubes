#!/usr/bin/env python3
"""Offline guards for the approval-gated credential rotation workflow.

This intentionally does not contact a cluster. Live preflight/start/finalize are separate,
attended operations and are never silently substituted by this check.
"""
from __future__ import annotations

import argparse
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "crossplane/tests/credential-rotation-workflow.sh"

class CheckError(ValueError):
    pass


def check(text: str) -> None:
    required = {
        "preflight": "preflight)",
        "provision": "provision)",
        "start": "start)",
        "prove overlap action": "prove-overlap)",
        "overlap role status": "status.credentials.activeRole",
        "overlap status guard": "CredentialOverlapActive",
        "overlap approval": "Prove active and previous credentials for the current overlap",
        "finalize": "finalize)",
        "stdin rotation": "--from-file=password=/dev/stdin",
        "approval gate": "APPROVE_MGMT=yes",
        "credential approval gate": "APPROVE_CREDENTIAL_ROTATION=yes",
        "refuse overwrite": "provision refuses overwrite",
        "provision rollback": "provision_cleanup",
        "exact source keys": "keys_are_exact",
        "consumer sweep": "consumer_sweep",
        "controller sweep": "cronjobs",
        "shared owner grant proof": "pg_has_role(current_user, 'app', 'member')",
        "role membership true": "$expected|true",
        "escaped proof substitution": r'\$(psql',
        "readback timeout": "TIMEOUT=${TIMEOUT:-900}",
        "annotation JSON lookup": "json.load(sys.stdin).get(\"metadata\",{}).get(\"annotations\",{}).get(sys.argv[1]",
        "previous RV annotation": "previous-credential-resource-version",
        "previous password digest": "previous-credential-digest",
        "patch digest argument": '"$previous_digest" "$id" "$now"',
        "rotation ID": "credential-rotation-id",
        "rotated timestamp": "credential-rotated-at",
        "expiry refusal": "refusing finalization before previousValidUntil",
        "temporary proof Secret": "rotation-proof-",
        "SecretKeyRef authentication": "secretKeyRef",
        "old credential negative proof": "old credential still authenticates",
        "digest change guard": "previous password digest did not change",
        "digest fingerprint": "password_digest",
        "base64 digest contract": "base64 Secret data string",
        "proof cleanup": "trap cleanup EXIT",
        "start overlap status": "wait_overlap_status",
        "final status": "wait_finalized_status",
        "finalized reason": "CredentialRotationFinalized",
        "start auth proof": "both active and previous credentials authenticate",
        "proof pod non-root": "runAsNonRoot: true",
        "proof pod seccomp": "seccompProfile: {type: RuntimeDefault}",
        "proof pod caps": "capabilities: {drop: [ALL]}",
    }
    for name, needle in required.items():
        if needle not in text:
            raise CheckError(f"missing {name}: {needle}")
    forbidden = {
        "secret in argv": re.compile(r"--from-literal=password|--password(?:=|\s)", re.I),
        "token in argv": re.compile(r"--token(?:=|\s)", re.I),
        "secret temp file": re.compile(r"password[^\n]*(?:>|>>)[^\n]*(?:tmp|/var/tmp)", re.I),
    }
    for name, pattern in forbidden.items():
        if pattern.search(text):
            raise CheckError(f"forbidden {name}")
    if any("args: [" in line and re.search(r"(?<!\\)\$\(", line) for line in text.splitlines()):
        raise CheckError("unescaped outer command substitution in proof Pod args")
    if "kubectl" not in text or "--kubeconfig" not in text:
        raise CheckError("workflow must use explicit management/workload kubeconfigs")
    print("PASS: credential workflow is approval-gated, stdin-only for passwords, double-buffered, and cleanup-bound")


def negative_controls(text: str) -> None:
    cases = [
        ("remove approval", text.replace('APPROVE_MGMT=yes', 'APPROVE_MGMT=no'), "APPROVE_MGMT=yes"),
        ("remove credential approval", text.replace('APPROVE_CREDENTIAL_ROTATION=yes', 'APPROVE_CREDENTIAL_ROTATION=no'), "APPROVE_CREDENTIAL_ROTATION=yes"),
        ("allow provision overwrite", text.replace('provision refuses overwrite', 'removed'), "provision refuses overwrite"),
        ("remove patch digest argument", text.replace('"$previous_digest" "$id" "$now"', '"$id" "$now"'), 'patch digest argument'),
        ("remove start overlap wait", text.replace('wait_overlap_status', 'removed'), 'wait_overlap_status'),
        ("remove prove-overlap action", text.replace('prove-overlap)', 'removed'), 'prove-overlap)'),
        ("remove overlap status guard", text.replace('CredentialOverlapActive', 'removed'), 'CredentialOverlapActive'),
        ("remove final status wait", text.replace('wait_finalized_status', 'removed'), 'wait_finalized_status'),
        ("remove proof pod hardening", text.replace('capabilities: {drop: [ALL]}', 'capabilities: {}'), 'capabilities: {drop: [ALL]}'),
        ("remove expiry guard", text.replace('refusing finalization before previousValidUntil', 'removed'), "previousValidUntil"),
        ("remove old-auth negative", text.replace('old credential still authenticates', 'removed'), "old credential still authenticates"),
        ("remove dormant controller sweep", text.replace('cronjobs', 'removed'), "cronjobs"),
        ("remove shared owner proof", text.replace("pg_has_role(current_user, 'app', 'member')", "current_user"), "pg_has_role(current_user, 'app', 'member')"),
        ("expect wrong boolean rendering", text.replace("$expected|true", "$expected|t"), "$expected|true"),
        ("unescaped outer substitution", text.replace(r'\$(psql', '$(psql'), r'\$(psql'),
        ("heartbeat timeout regression", text.replace("TIMEOUT=${TIMEOUT:-900}", "TIMEOUT=${TIMEOUT:-300}"), "TIMEOUT=${TIMEOUT:-900}"),
        ("broken annotation jsonpath", text.replace('json.load(sys.stdin).get(\"metadata\",{}).get(\"annotations\",{}).get(sys.argv[1]', "removed"), "json.load(sys.stdin).get(\"metadata\",{}).get(\"annotations\",{}).get(sys.argv[1]"),
        ("remove digest guard", text.replace('previous password digest did not change', 'removed'), "previous password digest did not change"),
        ("decode digest input", text.replace("base64 Secret data string", "decoded password bytes").replace(" | sha256sum", " | base64 -d | sha256sum"), "base64 Secret data string"),
        ("remove stdin", text.replace('--from-file=password=/dev/stdin', '--from-literal=password=bad'), '--from-file=password=/dev/stdin'),
    ]
    for name, mutated, expected in cases:
        try:
            check(mutated)
        except CheckError:
            print(f"NEGATIVE CONTROL PASS: {name}")
        else:
            raise CheckError(f"negative control did not fail: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    text = SCRIPT.read_text()
    if args.negative_controls:
        negative_controls(text)
    check(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
