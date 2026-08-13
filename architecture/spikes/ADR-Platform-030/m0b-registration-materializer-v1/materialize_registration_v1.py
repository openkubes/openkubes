#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


HERE = Path(__file__).resolve().parent
SPIKE = HERE.parent
PROJECT = SPIKE / "m0b-target-registration-v1/appproject-v5-candidate.yaml"
REGISTRATION = SPIKE / "m0b-target-registration-v1/cluster-registration-v5.template.yaml"
EXPECTED = {
    "name": "disposable-ok141",
    "namespaces": "ok-observability,kube-system",
    "project": "openkubes-disposable",
    "R": "sha256:636fe23404ac53109f44d6346534dcf1367ae91c572d5e18bd32cd0a3128a16e",
    "P": "sha256:b0f25c639a45d895b889997f5ecc2325db45dd5d51b0684998c94d5e17bd47bf",
    "fixtureDigest": "sha256:a2ae3437645db5a83426b89d36d00693d2600e4ef20dc1aba2650dcda7f936f6",
}
MAX_TOKEN_LIFETIME_SECONDS = 10800


class MaterializerError(ValueError):
    pass


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise MaterializerError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def require_sha256(value: str, field: str) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise MaterializerError(f"{field} must be a lowercase SHA-256 identity")


def validate_runtime(runtime: dict[str, Any], now: datetime) -> None:
    required = {
        "name", "server", "namespaces", "project", "clusterResources",
        "bearerToken", "caData", "capiClusterUID", "workloadKubeSystemUID",
        "workloadAPICAFingerprint", "tokenExpiration", "R", "P", "fixtureDigest",
    }
    if set(runtime) != required:
        raise MaterializerError(f"runtime fields mismatch: {sorted(set(runtime) ^ required)}")
    for key in ("name", "namespaces", "project", "R", "P", "fixtureDigest"):
        if runtime[key] != EXPECTED[key]:
            raise MaterializerError(f"runtime {key} mismatch")
    if runtime["clusterResources"] is not True:
        raise MaterializerError("clusterResources must be true")
    if not isinstance(runtime["server"], str) or not runtime["server"].startswith("https://"):
        raise MaterializerError("server must be HTTPS")
    for key in ("capiClusterUID", "workloadKubeSystemUID"):
        try:
            uuid.UUID(runtime[key])
        except (ValueError, TypeError, AttributeError) as error:
            raise MaterializerError(f"{key} must be a UUID") from error
    require_sha256(runtime["workloadAPICAFingerprint"], "workloadAPICAFingerprint")
    try:
        ca_bytes = base64.b64decode(runtime["caData"], validate=True)
    except Exception as error:
        raise MaterializerError("caData must be valid base64") from error
    if not ca_bytes or sha256_bytes(ca_bytes) != runtime["workloadAPICAFingerprint"]:
        raise MaterializerError("caData does not match workload API CA fingerprint")
    if not isinstance(runtime["bearerToken"], str) or len(runtime["bearerToken"]) < 20:
        raise MaterializerError("bearerToken is missing or implausibly short")
    expiration = parse_time(runtime["tokenExpiration"])
    lifetime = (expiration - now).total_seconds()
    if lifetime <= 0 or lifetime > MAX_TOKEN_LIFETIME_SECONDS:
        raise MaterializerError("token expiration is outside the bounded runtime window")


def validate_grant(grant: dict[str, Any], candidate_digest: str, now: datetime) -> None:
    spec = grant.get("spec", {})
    require_sha256(candidate_digest, "candidateDigest")
    if spec.get("decision") != "GO" or spec.get("materializerGranted") is not True:
        raise MaterializerError("materializer grant is absent")
    if spec.get("candidateDigest") != candidate_digest:
        raise MaterializerError("grant candidate digest mismatch")
    if spec.get("maximumRuns") != 1:
        raise MaterializerError("grant must bind exactly one run")
    if not isinstance(spec.get("grantID"), str) or not spec["grantID"].startswith("ok141-m0b-rm1-"):
        raise MaterializerError("grant ID mismatch")
    valid_from = parse_time(spec["validFrom"])
    valid_until = parse_time(spec["validUntil"])
    if not valid_from <= now <= valid_until or valid_until <= valid_from:
        raise MaterializerError("grant is outside its exact execution window")


def build_documents(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    project = yaml.safe_load(PROJECT.read_text())
    registration = yaml.safe_load(REGISTRATION.read_text())
    annotations = registration["metadata"]["annotations"]
    annotations["openkubes.io/capi-cluster-uid"] = runtime["capiClusterUID"]
    annotations["openkubes.io/workload-kube-system-uid"] = runtime["workloadKubeSystemUID"]
    annotations["openkubes.io/workload-api-ca-sha256"] = runtime["workloadAPICAFingerprint"]
    annotations["openkubes.io/token-expiration"] = runtime["tokenExpiration"]
    data = registration["stringData"]
    data["server"] = runtime["server"]
    data["config"] = json.dumps(
        {
            "bearerToken": runtime["bearerToken"],
            "tlsClientConfig": {"insecure": False, "caData": runtime["caData"]},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return [project, registration]


def serialize_documents(documents: list[dict[str, Any]]) -> bytes:
    return yaml.safe_dump_all(documents, explicit_start=True, sort_keys=False).encode()


def redacted_result(runtime: dict[str, Any], mode: str, **extra: Any) -> dict[str, Any]:
    result = {
        "mode": mode,
        "name": runtime["name"],
        "server": runtime["server"],
        "capiClusterUID": runtime["capiClusterUID"],
        "workloadKubeSystemUID": runtime["workloadKubeSystemUID"],
        "workloadAPICAFingerprint": runtime["workloadAPICAFingerprint"],
        "tokenExpiration": runtime["tokenExpiration"],
        "credentialRetained": False,
        "credentialPrinted": False,
    }
    result.update(extra)
    return result


def execute(runtime: dict[str, Any], kubectl: str, kubeconfig: Path) -> dict[str, Any]:
    documents = serialize_documents(build_documents(runtime))
    command = [kubectl, "--kubeconfig", str(kubeconfig), "create", "-f", "-"]
    completed = subprocess.run(
        command,
        input=documents,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        env=os.environ.copy(),
    )
    result = redacted_result(
        runtime,
        "execute",
        exitCode=completed.returncode,
        submittedObjectCount=2,
        stdoutDigest=sha256_bytes(completed.stdout),
        stderrDigest=sha256_bytes(completed.stderr),
    )
    documents = b""
    if completed.returncode != 0:
        raise MaterializerError("kubectl create failed; raw stdout and stderr are intentionally suppressed")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-input-only", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--grant-file", type=Path)
    parser.add_argument("--candidate-digest")
    parser.add_argument("--kubectl", default="kubectl")
    parser.add_argument("--kubeconfig", type=Path)
    args = parser.parse_args()
    try:
        if args.verify_input_only == args.execute:
            raise MaterializerError("select exactly one mode")
        runtime = json.load(sys.stdin)
        now = datetime.now(timezone.utc)
        validate_runtime(runtime, now)
        if args.verify_input_only:
            print(json.dumps(redacted_result(runtime, "verify-input-only"), sort_keys=True, separators=(",", ":")))
            return 0
        if not args.grant_file or not args.candidate_digest or not args.kubeconfig:
            raise MaterializerError("execute requires grant file candidate digest and kubeconfig")
        grant = yaml.safe_load(args.grant_file.read_text())
        validate_grant(grant, args.candidate_digest, now)
        print(json.dumps(execute(runtime, args.kubectl, args.kubeconfig), sort_keys=True, separators=(",", ":")))
        return 0
    except (MaterializerError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
