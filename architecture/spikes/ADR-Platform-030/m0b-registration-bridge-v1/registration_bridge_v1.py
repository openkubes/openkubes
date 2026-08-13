#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
TOKEN_UTILITY = HERE.parent / "m0b-tokenrequest-antireplay-v1/tokenrequest_antireplay_v1.py"
MATERIALIZER = HERE.parent / "m0b-registration-materializer-v1/materialize_registration_v1.py"
EXPECTED_RUNTIME_FIELDS = {
    "name", "server", "namespaces", "project", "clusterResources", "caData",
    "capiClusterUID", "workloadKubeSystemUID", "workloadAPICAFingerprint",
    "R", "P", "fixtureDigest",
}


class BridgeError(ValueError):
    pass


def load_grant(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())["spec"]


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise BridgeError("grant timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def validate_pair(token: dict[str, Any], materializer: dict[str, Any], candidate_digest: str, now: datetime) -> None:
    if token.get("pairedGrantID") != materializer.get("grantID"):
        raise BridgeError("token grant does not bind materializer grant")
    if materializer.get("pairedGrantID") != token.get("grantID"):
        raise BridgeError("materializer grant does not bind token grant")
    for spec, expected_prefix, required_flag in (
        (token, "ok141-m0b-tr1-", "tokenRequestGranted"),
        (materializer, "ok141-m0b-rm1-", "materializerGranted"),
    ):
        if spec.get("decision") != "GO" or spec.get(required_flag) is not True:
            raise BridgeError("paired subgrant is not GO")
        if spec.get("candidateDigest") != candidate_digest or spec.get("maximumRuns") != 1:
            raise BridgeError("paired subgrant scope mismatch")
        if not isinstance(spec.get("grantID"), str) or not spec["grantID"].startswith(expected_prefix):
            raise BridgeError("paired subgrant ID mismatch")
        start = parse_time(spec["validFrom"])
        end = parse_time(spec["validUntil"])
        if end <= start or not start <= now <= end:
            raise BridgeError("paired subgrant is outside its exact window")
    for key in ("candidateDigest", "maximumRuns", "validFrom", "validUntil"):
        if token.get(key) != materializer.get(key):
            raise BridgeError(f"paired subgrant mismatch: {key}")


def validate_runtime(runtime: dict[str, Any], token_grant: dict[str, Any]) -> None:
    if set(runtime) != EXPECTED_RUNTIME_FIELDS:
        raise BridgeError("runtime envelope fields mismatch")
    correlations = {
        "capiClusterUID": "capiClusterUID",
        "workloadKubeSystemUID": "workloadKubeSystemUID",
        "workloadAPICAFingerprint": "workloadAPICAFingerprint",
    }
    for runtime_key, grant_key in correlations.items():
        if runtime[runtime_key] != token_grant.get(grant_key):
            raise BridgeError(f"runtime/grant correlation mismatch: {runtime_key}")


def run_child(command: list[str], input_bytes: bytes | None = None, pass_fds: tuple[int, ...] = ()) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        pass_fds=pass_fds,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=90,
    )


def execute(args: argparse.Namespace, runtime: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    token_grant = load_grant(args.token_grant_file)
    materializer_grant = load_grant(args.materializer_grant_file)
    validate_pair(token_grant, materializer_grant, args.candidate_digest, now)
    validate_runtime(runtime, token_grant)

    read_fd, write_fd = os.pipe()
    try:
        token_child = run_child(
            [
                sys.executable, str(TOKEN_UTILITY), "--execute",
                "--grant-file", str(args.token_grant_file),
                "--candidate-digest", args.candidate_digest,
                "--receipt", str(args.receipt),
                "--token-sink-fd", str(write_fd),
                "--audience", token_grant["audience"],
                "--kubectl", args.target_kubectl,
                "--kubeconfig", str(args.target_kubeconfig),
            ],
            pass_fds=(write_fd,),
        )
        os.close(write_fd)
        write_fd = -1
        token = os.read(read_fd, 65536)
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
    if token_child.returncode != 0:
        token = b""
        raise BridgeError("TokenRequest child failed; raw child output is suppressed")
    if len(token) < 20:
        raise BridgeError("TokenRequest child returned no usable pipe value")
    try:
        token_result = json.loads(token_child.stdout)
        materializer_input = dict(runtime)
        materializer_input["bearerToken"] = token.decode()
        materializer_input["tokenExpiration"] = token_result["expirationTimestamp"]
        materializer_child = run_child(
            [
                sys.executable, str(MATERIALIZER), "--execute",
                "--grant-file", str(args.materializer_grant_file),
                "--candidate-digest", args.candidate_digest,
                "--kubectl", args.shared_kubectl,
                "--kubeconfig", str(args.shared_kubeconfig),
            ],
            input_bytes=json.dumps(materializer_input, sort_keys=True, separators=(",", ":")).encode(),
        )
    finally:
        token = b""
        if "materializer_input" in locals():
            materializer_input["bearerToken"] = ""
    if materializer_child.returncode != 0:
        raise BridgeError("registration materializer child failed; raw child output is suppressed")
    materializer_result = json.loads(materializer_child.stdout)
    return {
        "state": "REGISTRATION-CREATED",
        "candidateDigest": args.candidate_digest,
        "tokenGrantID": token_grant["grantID"],
        "materializerGrantID": materializer_grant["grantID"],
        "consumptionReceiptDigest": token_result["consumptionReceiptDigest"],
        "tokenExpiration": token_result["expirationTimestamp"],
        "submittedObjectCount": materializer_result["submittedObjectCount"],
        "credentialPrinted": False,
        "credentialRetainedByBridge": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--token-grant-file", type=Path)
    parser.add_argument("--materializer-grant-file", type=Path)
    parser.add_argument("--candidate-digest")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--target-kubectl", default="kubectl")
    parser.add_argument("--target-kubeconfig", type=Path)
    parser.add_argument("--shared-kubectl", default="kubectl")
    parser.add_argument("--shared-kubeconfig", type=Path)
    args = parser.parse_args()
    try:
        if not args.execute:
            raise BridgeError("execution mode requires explicit future paired grants")
        required = (
            args.token_grant_file, args.materializer_grant_file, args.candidate_digest,
            args.receipt, args.target_kubeconfig, args.shared_kubeconfig,
        )
        if any(value is None for value in required):
            raise BridgeError("bridge execution arguments are incomplete")
        runtime = json.load(sys.stdin)
        print(json.dumps(execute(args, runtime), sort_keys=True, separators=(",", ":")))
        return 0
    except (BridgeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
