#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SERVICE_ACCOUNT = "ok141-argocd-manager"
NAMESPACE = "kube-system"
MAX_EXPIRATION_SECONDS = 10800


class GateError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise GateError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def validate_grant(grant: dict[str, Any], candidate_digest: str, audience: str, now: datetime) -> dict[str, Any]:
    spec = grant.get("spec", {})
    if spec.get("decision") != "GO":
        raise GateError("grant decision is not GO")
    for key in ("tokenRequestGranted", "antiReplayReceiptGranted"):
        if spec.get(key) is not True:
            raise GateError(f"{key} is not granted")
    if spec.get("candidateDigest") != candidate_digest:
        raise GateError("candidate digest mismatch")
    if spec.get("maximumRuns") != 1:
        raise GateError("grant must bind exactly one run")
    if not isinstance(spec.get("grantID"), str) or not spec["grantID"].startswith("ok141-m0b-tr1-"):
        raise GateError("grant ID mismatch")
    if spec.get("serviceAccount") != f"{NAMESPACE}/{SERVICE_ACCOUNT}":
        raise GateError("service account mismatch")
    if spec.get("audience") != audience:
        raise GateError("TokenRequest audience mismatch")
    if spec.get("expirationSeconds") != MAX_EXPIRATION_SECONDS:
        raise GateError("TokenRequest expiration mismatch")
    valid_from = parse_time(spec["validFrom"])
    valid_until = parse_time(spec["validUntil"])
    if valid_until <= valid_from or not valid_from <= now <= valid_until:
        raise GateError("grant is outside its exact execution window")
    for key in ("capiClusterUID", "workloadKubeSystemUID", "workloadAPICAFingerprint"):
        if not isinstance(spec.get(key), str) or spec[key].startswith("RUNTIME-"):
            raise GateError(f"grant runtime identity is unbound: {key}")
    return spec


def consume_once(receipt: Path, grant: dict[str, Any], candidate_digest: str, now: datetime) -> str:
    payload = {
        "apiVersion": "evidence.openkubes.io/v1alpha1",
        "kind": "GrantConsumptionReceipt",
        "grantID": grant["grantID"],
        "candidateDigest": candidate_digest,
        "consumedAt": now.isoformat().replace("+00:00", "Z"),
        "state": "CONSUMED-BEFORE-TOKENREQUEST",
        "maximumRuns": 1,
        "containsCredential": False,
    }
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    try:
        descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise GateError("grant consumption receipt already exists") from error
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return sha256_bytes(raw)


def require_pipe(descriptor: int) -> None:
    if descriptor in (0, 1, 2):
        raise GateError("token sink must not be stdin stdout or stderr")
    mode = os.fstat(descriptor).st_mode
    if not (stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)):
        raise GateError("token sink must be an anonymous pipe or socket")


def request_token(kubectl: str, kubeconfig: Path, audience: str) -> tuple[bytes, str]:
    request = {
        "apiVersion": "authentication.k8s.io/v1",
        "kind": "TokenRequest",
        "spec": {"audiences": [audience], "expirationSeconds": MAX_EXPIRATION_SECONDS},
    }
    endpoint = f"/api/v1/namespaces/{NAMESPACE}/serviceaccounts/{SERVICE_ACCOUNT}/token"
    completed = subprocess.run(
        [kubectl, "--kubeconfig", str(kubeconfig), "create", "--raw", endpoint, "-f", "-"],
        input=json.dumps(request, sort_keys=True, separators=(",", ":")).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise GateError("TokenRequest failed; raw stdout and stderr are intentionally suppressed")
    try:
        response = json.loads(completed.stdout)
        token = response["status"]["token"].encode()
        expiration = response["status"]["expirationTimestamp"]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise GateError("TokenRequest response is malformed; raw response is suppressed") from error
    if len(token) < 20:
        raise GateError("TokenRequest returned an implausibly short token")
    expiry = parse_time(expiration)
    now = datetime.now(timezone.utc)
    remaining = (expiry - now).total_seconds()
    if remaining <= 0 or remaining > MAX_EXPIRATION_SECONDS + 60:
        raise GateError("TokenRequest response expiration is outside the bounded window")
    return token, expiration


def execute(args: argparse.Namespace) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    grant = yaml.safe_load(args.grant_file.read_text())
    spec = validate_grant(grant, args.candidate_digest, args.audience, now)
    require_pipe(args.token_sink_fd)
    receipt_digest = consume_once(args.receipt, spec, args.candidate_digest, now)
    token, expiration = request_token(args.kubectl, args.kubeconfig, args.audience)
    try:
        written = os.write(args.token_sink_fd, token)
        if written != len(token):
            raise GateError("token pipe write was incomplete")
    finally:
        token = b""
    return {
        "state": "TOKEN-ISSUED-TO-PIPE",
        "grantID": spec["grantID"],
        "candidateDigest": args.candidate_digest,
        "serviceAccount": f"{NAMESPACE}/{SERVICE_ACCOUNT}",
        "audience": args.audience,
        "expirationTimestamp": expiration,
        "consumptionReceiptDigest": receipt_digest,
        "credentialPrinted": False,
        "credentialRetainedByUtility": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--grant-file", type=Path)
    parser.add_argument("--candidate-digest")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--token-sink-fd", type=int)
    parser.add_argument("--audience")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--kubeconfig", type=Path)
    args = parser.parse_args()
    try:
        if not args.execute:
            raise GateError("execution mode requires an explicit future grant")
        if any(value is None for value in (
            args.grant_file, args.candidate_digest, args.receipt, args.token_sink_fd,
            args.audience, args.kubeconfig,
        )):
            raise GateError("execute arguments are incomplete")
        result = execute(args)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (GateError, KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
