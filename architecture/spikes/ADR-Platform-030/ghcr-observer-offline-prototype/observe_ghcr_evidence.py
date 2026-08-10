#!/usr/bin/env python3
"""Read-only GHCR digest observer with a deterministic offline evaluation core."""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


EXPECTED_REPOSITORY = "ghcr.io/openkubes/ok141-evidence"
INDEX_VERSION = "ok141-active-evidence-index/v1"
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE_RE = re.compile(r"[0-9a-f]{40}\Z")
INDEX_KEYS = {
    "version",
    "repository",
    "ociManifestDigest",
    "internalBundleDigest",
    "retainedUntil",
    "workflowSourceRevision",
}
OBSERVATION_KEYS = {"status", "repository", "requestedDigest", "observedDigest", "observedAtUTC", "reason"}


class ObserverError(ValueError):
    """A fail-closed observer input or evaluation error."""


def _utc(value: str) -> dt.datetime:
    if not value.endswith("Z"):
        raise ObserverError("timestamp must be RFC3339 UTC")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ObserverError("invalid RFC3339 UTC timestamp") from exc
    if parsed.tzinfo != dt.timezone.utc:
        raise ObserverError("timestamp must use UTC")
    return parsed


def load_index(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or set(data) != INDEX_KEYS:
        raise ObserverError("active evidence index has unexpected fields")
    if data["version"] != INDEX_VERSION or data["repository"] != EXPECTED_REPOSITORY:
        raise ObserverError("active evidence index identity mismatch")
    for field in ("ociManifestDigest", "internalBundleDigest"):
        if not isinstance(data[field], str) or not DIGEST_RE.fullmatch(data[field]):
            raise ObserverError(f"active evidence index {field} is not an exact SHA-256 digest")
    if not isinstance(data["workflowSourceRevision"], str) or not SOURCE_RE.fullmatch(data["workflowSourceRevision"]):
        raise ObserverError("active evidence index workflowSourceRevision is not a full commit SHA")
    _utc(data["retainedUntil"])
    return data


def validate_observation(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != OBSERVATION_KEYS:
        raise ObserverError("observation has unexpected fields")
    if data["status"] not in {"PRESENT", "MISSING", "DENIED", "UNVERIFIABLE"}:
        raise ObserverError("observation status is invalid")
    if data["repository"] != EXPECTED_REPOSITORY:
        raise ObserverError("observation repository mismatch")
    if not DIGEST_RE.fullmatch(str(data["requestedDigest"])):
        raise ObserverError("observation requested digest is invalid")
    if data["observedDigest"] is not None and not DIGEST_RE.fullmatch(str(data["observedDigest"])):
        raise ObserverError("observation returned digest is invalid")
    _utc(data["observedAtUTC"])
    if not isinstance(data["reason"], str) or not data["reason"]:
        raise ObserverError("observation reason is required")
    return data


def evaluate(index: dict[str, Any], observation: dict[str, Any], now: dt.datetime | None = None) -> dict[str, Any]:
    observation = validate_observation(observation)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo != dt.timezone.utc:
        raise ObserverError("evaluation clock must use UTC")
    status = "OBSERVED-PRESENT"
    reason = "ExactDigestPresent"
    if observation["requestedDigest"] != index["ociManifestDigest"]:
        status, reason = "FAILED", "RequestedDigestMismatch"
    elif observation["status"] != "PRESENT":
        status, reason = "FAILED", {
            "MISSING": "DigestMissing",
            "DENIED": "PackageReadDenied",
            "UNVERIFIABLE": "EvidenceUnverifiable",
        }[observation["status"]]
    elif observation["observedDigest"] != index["ociManifestDigest"]:
        status, reason = "FAILED", "ObservedDigestMismatch"
    elif now > _utc(index["retainedUntil"]):
        status, reason = "FAILED", "RetentionWindowExpired"
    return {
        "version": "ok141-observer-result/v1",
        "status": status,
        "reason": reason,
        "repository": index["repository"],
        "ociManifestDigest": index["ociManifestDigest"],
        "internalBundleDigest": index["internalBundleDigest"],
        "workflowSourceRevision": index["workflowSourceRevision"],
        "observedAtUTC": observation["observedAtUTC"],
        "evaluatedAtUTC": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def _challenge(value: str) -> tuple[str, str, str]:
    match = re.fullmatch(r'Bearer realm="([^"]+)",service="([^"]+)",scope="([^"]+)"', value)
    if not match:
        raise ObserverError("registry authentication challenge is unsupported")
    realm, service, scope = match.groups()
    parsed = urllib.parse.urlparse(realm)
    if parsed.scheme != "https" or parsed.hostname != "ghcr.io":
        raise ObserverError("registry token realm is not trusted")
    if service != "ghcr.io" or scope != "repository:openkubes/ok141-evidence:pull":
        raise ObserverError("registry authentication scope mismatch")
    return realm, service, scope


def observe_live(
    digest: str,
    username: str,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    if not DIGEST_RE.fullmatch(digest):
        raise ObserverError("live observation digest is invalid")
    if not username or not token:
        raise ObserverError("GHCR read credential is missing")
    manifest_url = f"https://ghcr.io/v2/openkubes/ok141-evidence/manifests/{digest}"
    headers = {"Accept": "application/vnd.oci.image.manifest.v1+json"}
    try:
        opener(urllib.request.Request(manifest_url, method="HEAD", headers=headers), timeout=30)
        raise ObserverError("unauthenticated GHCR access is outside the reviewed private-package model")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return _observation("MISSING", digest, None, "DigestMissing")
        if exc.code != 401:
            return _observation("UNVERIFIABLE", digest, None, f"RegistryHTTP{exc.code}")
        realm, service, scope = _challenge(exc.headers.get("WWW-Authenticate", ""))

    query = urllib.parse.urlencode({"service": service, "scope": scope})
    auth = base64.b64encode(f"{username}:{token}".encode()).decode()
    token_request = urllib.request.Request(f"{realm}?{query}", headers={"Authorization": f"Basic {auth}"})
    try:
        with opener(token_request, timeout=30) as response:
            bearer = json.load(response).get("token")
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return _observation("DENIED", digest, None, "TokenExchangeFailed")
    if not bearer:
        return _observation("DENIED", digest, None, "TokenMissing")

    request = urllib.request.Request(manifest_url, method="HEAD", headers={**headers, "Authorization": f"Bearer {bearer}"})
    try:
        with opener(request, timeout=30) as response:
            observed = response.headers.get("Docker-Content-Digest")
    except urllib.error.HTTPError as exc:
        status = "MISSING" if exc.code == 404 else "DENIED" if exc.code in {401, 403} else "UNVERIFIABLE"
        return _observation(status, digest, None, f"RegistryHTTP{exc.code}")
    except urllib.error.URLError:
        return _observation("UNVERIFIABLE", digest, None, "RegistryUnavailable")
    return _observation("PRESENT", digest, observed, "ManifestHeadSucceeded")


def _observation(status: str, requested: str, observed: str | None, reason: str) -> dict[str, Any]:
    return {
        "status": status,
        "repository": EXPECTED_REPOSITORY,
        "requestedDigest": requested,
        "observedDigest": observed,
        "observedAtUTC": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "reason": reason,
    }


def render_summary(result: dict[str, Any]) -> str:
    return "\n".join(
        (
            "# OK-141 evidence observation",
            "",
            f"- Status: `{result['status']}`",
            f"- Reason: `{result['reason']}`",
            f"- Repository: `{result['repository']}`",
            f"- OCI manifest digest: `{result['ociManifestDigest']}`",
            f"- Internal bundle digest: `{result['internalBundleDigest']}`",
            f"- Workflow source revision: `{result['workflowSourceRevision']}`",
            f"- Observed at UTC: `{result['observedAtUTC']}`",
            f"- Evaluated at UTC: `{result['evaluatedAtUTC']}`",
            "- Remediation authority: `NONE-AUTOMATIC`",
            "",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--observation-file", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        index = load_index(args.index)
        if args.observation_file:
            observation = json.loads(args.observation_file.read_text())
        else:
            observation = observe_live(index["ociManifestDigest"], os.environ.get("GHCR_USERNAME", ""), os.environ.get("GHCR_TOKEN", ""))
        result = evaluate(index, observation)
        rendered = render_summary(result)
        if args.summary:
            args.summary.write_text(rendered)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["status"] == "OBSERVED-PRESENT" else 2
    except (ObserverError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
