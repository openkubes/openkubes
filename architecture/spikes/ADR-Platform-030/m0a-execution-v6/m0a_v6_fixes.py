#!/usr/bin/env python3
"""Pure helpers for the M0a-v6 admission and time-boundary amendments."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml


class FixError(ValueError):
    pass


def sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def amend_admission_manifest(amendment_path: Path) -> bytes:
    amendment = yaml.safe_load(amendment_path.read_text())["spec"]
    if amendment["version"] != "ok141-m0a-admission-expression-amendment/v1":
        raise FixError("unsupported amendment version")
    base = (amendment_path.parent / amendment["base"]["path"]).resolve()
    if not base.is_file() or sha(base) != amendment["base"]["digest"]:
        raise FixError("base admission manifest identity mismatch")
    raw = base.read_text()
    replacement = amendment["exactReplacement"]
    old = replacement["old"]
    new = replacement["new"]
    required = replacement["occurrencesRequired"]
    if raw.count(old) != required or required != 1:
        raise FixError("admission expression replacement is not exact")
    amended = raw.replace(old, new)
    documents = list(yaml.safe_load_all(amended))
    if len(documents) != 2:
        raise FixError("amended admission bootstrap must contain exactly two objects")
    policy, binding = documents
    if policy.get("kind") != "ValidatingAdmissionPolicy" or binding.get("kind") != "ValidatingAdmissionPolicyBinding":
        raise FixError("amended admission object kinds changed")
    if policy["spec"].get("failurePolicy") != "Fail":
        raise FixError("admission failure policy changed")
    expression = policy["spec"]["validations"][0]["expression"]
    if old in expression or new not in expression:
        raise FixError("presence-guarded expression missing")
    rendered = amended.encode()
    identity = amendment["expectedRenderedIdentity"]
    rendered_digest = "sha256:" + hashlib.sha256(rendered).hexdigest()
    if rendered_digest != identity["digest"] or len(rendered) != identity["sizeBytes"]:
        raise FixError("amended admission manifest identity mismatch")
    return rendered


def wait_until_not_before(
    boundary: datetime,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> datetime:
    """Return only after the supplied wall clock reaches the exact boundary."""

    if boundary.tzinfo is None:
        raise FixError("boundary must be timezone-aware")
    while True:
        sampled = now()
        if sampled.tzinfo is None:
            raise FixError("clock sample must be timezone-aware")
        remaining = (boundary - sampled).total_seconds()
        if remaining <= 0:
            return sampled
        sleep(remaining)
