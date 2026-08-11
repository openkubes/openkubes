#!/usr/bin/env python3
"""Credential-free GHCR observer with anonymous pull-token exchange."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


HERE = Path(__file__).resolve().parent
V1_PATH = HERE.parent / "ghcr-observer-offline-prototype" / "observe_ghcr_evidence.py"
SPEC = importlib.util.spec_from_file_location("ok141_ghcr_observer_v1_runtime", V1_PATH)
V1 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = V1
assert SPEC.loader is not None
SPEC.loader.exec_module(V1)


def observed(
    status: str,
    requested: str,
    digest: str | None,
    reason: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo != dt.timezone.utc:
        raise V1.ObserverError("observation clock must use UTC")
    return {
        "status": status,
        "repository": V1.EXPECTED_REPOSITORY,
        "requestedDigest": requested,
        "observedDigest": digest,
        "observedAtUTC": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reason": reason,
    }


def observe_public(
    digest: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    if not V1.DIGEST_RE.fullmatch(digest):
        raise V1.ObserverError("live observation digest is invalid")
    manifest_url = f"https://ghcr.io/v2/openkubes/ok141-evidence/manifests/{digest}"
    headers = {"Accept": "application/vnd.oci.image.manifest.v1+json"}

    try:
        with opener(urllib.request.Request(manifest_url, method="HEAD", headers=headers), timeout=30) as response:
            returned = response.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return observed("MISSING", digest, None, "DigestMissing", now)
        if exc.code == 403:
            return observed("DENIED", digest, None, "PackageReadDenied", now)
        if exc.code != 401:
            return observed("UNVERIFIABLE", digest, None, f"RegistryHTTP{exc.code}", now)
        try:
            realm, service, scope = V1._challenge(exc.headers.get("WWW-Authenticate", ""))
        except V1.ObserverError:
            return observed("DENIED", digest, None, "RegistryChallengeRejected", now)
        query = urllib.parse.urlencode({"service": service, "scope": scope})
        try:
            with opener(urllib.request.Request(f"{realm}?{query}"), timeout=30) as response:
                bearer = json.load(response).get("token")
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return observed("DENIED", digest, None, "AnonymousTokenExchangeFailed", now)
        if not bearer:
            return observed("DENIED", digest, None, "AnonymousTokenMissing", now)
        authenticated = urllib.request.Request(
            manifest_url,
            method="HEAD",
            headers={**headers, "Authorization": f"Bearer {bearer}"},
        )
        try:
            with opener(authenticated, timeout=30) as response:
                returned = response.headers.get("Docker-Content-Digest")
        except urllib.error.HTTPError as second:
            if second.code == 404:
                return observed("MISSING", digest, None, "DigestMissing", now)
            if second.code in {401, 403}:
                return observed("DENIED", digest, None, "PackageReadDenied", now)
            return observed("UNVERIFIABLE", digest, None, f"RegistryHTTP{second.code}", now)
        except urllib.error.URLError:
            return observed("UNVERIFIABLE", digest, None, "RegistryUnavailable", now)
    except urllib.error.URLError:
        return observed("UNVERIFIABLE", digest, None, "RegistryUnavailable", now)

    if not returned:
        return observed("UNVERIFIABLE", digest, None, "DigestHeaderMissing", now)
    return observed("PRESENT", digest, returned, "AnonymousManifestHeadSucceeded", now)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--observation-file", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        index = V1.load_index(args.index)
        observation = json.loads(args.observation_file.read_text()) if args.observation_file else observe_public(index["ociManifestDigest"])
        result = V1.evaluate(index, observation)
        summary = V1.render_summary(result)
        if args.summary:
            args.summary.write_text(summary)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "OBSERVED-PRESENT" else 2
    except (V1.ObserverError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
