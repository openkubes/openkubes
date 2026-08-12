#!/usr/bin/env python3
"""Verify the exact Kubernetes v1.34.1 source evidence used by M0a v4."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

import yaml


class VerificationError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def expect(actual: Any, expected: Any, claim: str) -> None:
    if actual != expected:
        raise VerificationError(f"{claim}: expected {expected!r}, got {actual!r}")


def verify(path: Path) -> str:
    spec = yaml.safe_load(path.read_text())["spec"]
    expect(spec["version"], "ok141-m0a-v4-upstream-semantics/v1", "version")
    expect(spec["state"], "OFFLINE-PRIMARY-SOURCE-EVIDENCE", "state")
    expect(spec["upstream"], {
        "repository": "https://github.com/kubernetes/kubernetes",
        "tag": "v1.34.1",
        "commit": "93248f9ae092f571eb870b7664c534bfc7d00f03",
    }, "upstream identity")
    expect(spec["serverSideApply"]["sources"], [
        {
            "path": "staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go",
            "fileDigest": "sha256:78d9deec5eee8d3206fd56a566ffcef7f9c70b08059305bd6efb7fc38d409037",
            "relevantSymbol": "types.ApplyPatchType",
        },
        {
            "path": "staging/src/k8s.io/apimachinery/pkg/types/patch.go",
            "fileDigest": "sha256:89f33a9d09be319ad831bb2e539d5afaec29ca7e76ec8ab04064de65829d9977",
            "relevantSymbol": "ApplyPatchType",
        },
    ], "server-side apply source set")
    expect(spec["serverSideApply"]["v3RolePatchAllowed"], False, "v3 patch authorization")

    token = spec["tokenExpiry"]
    expect(token["jwtValidation"]["defaultLeewaySeconds"], 60, "JWT leeway")
    expect(token["jwtValidation"]["fileDigest"], "sha256:f94beffcd3e4d1adbafbdd19027ac2632f7477a1a76cfc1e6ed657a929522d28", "JWT validation source")
    expect(token["serviceAccountClaims"]["fileDigest"], "sha256:55172a6b9115887752682fb4e23b6660414ad8ed671c0395cc5acf7d81bd25c1", "service-account claims source")
    expect(token["authenticationOptions"]["defaultSuccessCacheSeconds"], 10, "successful-authentication cache")
    expect(token["authenticationOptions"]["fileDigest"], "sha256:a8dd9b0f1ec1213b7ff5806c83612f020d54c73b9ad1c09765f6a71210b1fb89", "authentication options source")
    expect(token["authenticationWiring"]["fileDigest"], "sha256:a55b2ef73274ea5117381d2a3aaebb7713c1d3e30b7856b4e112611a543e0dad", "authentication wiring source")
    expect(token["cacheImplementation"]["fileDigest"], "sha256:e77736c74014daa1d774d8073ab72246a596a9df8dad921de0203e95548ca6cc", "cache implementation source")

    derived = spec["derivedObservationBoundary"]
    expect(derived["jwtLeewaySeconds"], 60, "derived JWT leeway")
    expect(derived["successCacheSeconds"], 10, "derived cache")
    expect(derived["observationAndClockToleranceSeconds"], 30, "derived tolerance")
    expect(derived["rejectionDeadlineOffsetSeconds"], 100, "derived rejection deadline")
    expect(derived["formula"], "60+10+30", "deadline formula")
    expect(derived["immediateRevocationClaim"], False, "immediate revocation claim")
    return sha(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--digest-file", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evidence.resolve())
        if args.digest_file:
            expect(args.digest_file.read_text().strip(), result, "evidence digest")
        print(result)
        return 0
    except (OSError, KeyError, TypeError, ValueError, VerificationError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
