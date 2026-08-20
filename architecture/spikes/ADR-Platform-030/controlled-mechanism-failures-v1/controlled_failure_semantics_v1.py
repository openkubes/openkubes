#!/usr/bin/env python3
"""Fail-closed evaluation semantics for OK-141 controlled failures."""

from __future__ import annotations

import datetime as dt
from typing import Any


APPLICATIONS = {
    "disposable-ok141-observability-core",
    "disposable-ok141-observability-alerting",
    "disposable-ok141-observability-dashboards",
}

APPLICATION_PATHS = {
    "disposable-ok141-observability-core": "profiles/ok-observability-standard",
    "disposable-ok141-observability-alerting": "alerting",
    "disposable-ok141-observability-dashboards": "dashboards",
}

NON_BLOCKING_APPLICATION_CONDITIONS = {"OrphanedResourceWarning"}


def _condition(obj: dict[str, Any], condition_type: str) -> dict[str, Any]:
    return next(
        (
            item
            for item in obj.get("status", {}).get("conditions", [])
            if item.get("type") == condition_type
        ),
        {},
    )


def _current_true(obj: dict[str, Any], condition_type: str) -> bool:
    generation = obj.get("metadata", {}).get("generation")
    condition = _condition(obj, condition_type)
    return (
        isinstance(generation, int)
        and condition.get("status") == "True"
        and condition.get("observedGeneration") == generation
    )


def network_ready(
    hcp: dict[str, Any],
    hrps: list[dict[str, Any]],
    *,
    expected_version: str = "1.19.6",
    runtime_ready: bool,
) -> bool:
    """Return true only when desired E and authoritative runtime agree."""
    if hcp.get("spec", {}).get("version") != expected_version:
        return False
    if not all(
        _current_true(hcp, condition)
        for condition in (
            "Ready",
            "HelmReleaseProxySpecsUpToDate",
            "HelmReleaseProxiesReady",
        )
    ):
        return False
    if len(hrps) != 1:
        return False
    hrp = hrps[0]
    if hrp.get("spec", {}).get("version") != expected_version:
        return False
    if not all(
        _current_true(hrp, condition)
        for condition in ("Ready", "HelmReleaseReady")
    ):
        return False
    return runtime_ready


def platform_ready(
    applications: list[dict[str, Any]],
    *,
    expected_revision: str,
    minimum_reconciled_at: str | None = None,
) -> bool:
    """Return true only for the exact desired, current, healthy Argo set.

    Argo CD Application status does not expose ``observedGeneration`` in the
    live version used by OK-141. Freshness is therefore proven from the exact
    desired source projection plus an optional bounded ``reconciledAt`` fence.
    A warning about orphaned resources is informational for this profile; all
    other Application conditions remain fail-closed.
    """
    if {item.get("metadata", {}).get("name") for item in applications} != APPLICATIONS:
        return False
    freshness_fence = _timestamp(minimum_reconciled_at) if minimum_reconciled_at else None
    if minimum_reconciled_at and freshness_fence is None:
        return False
    for application in applications:
        name = application.get("metadata", {}).get("name")
        if not application_ready(
            application,
            expected_revision=expected_revision,
            expected_path=APPLICATION_PATHS.get(name),
            minimum_reconciled_at=minimum_reconciled_at,
        ):
            return False
    return True


def application_ready(
    application: dict[str, Any],
    *,
    expected_revision: str,
    expected_path: str | None,
    minimum_reconciled_at: str | None = None,
) -> bool:
    """Evaluate one exact Argo Application without claiming repair ownership."""
    if not expected_path:
        return False
    source = application.get("spec", {}).get("source", {})
    status = application.get("status", {})
    if source.get("targetRevision") != expected_revision:
        return False
    if source.get("path") != expected_path:
        return False
    blocking_conditions = {
        item.get("type")
        for item in status.get("conditions", [])
        if item.get("type") not in NON_BLOCKING_APPLICATION_CONDITIONS
    }
    if blocking_conditions:
        return False
    if minimum_reconciled_at is not None:
        fence = _timestamp(minimum_reconciled_at)
        reconciled_at = _timestamp(status.get("reconciledAt"))
        if fence is None or reconciled_at is None or reconciled_at < fence:
            return False
    return (
        status.get("sync", {}).get("status") == "Synced"
        and status.get("sync", {}).get("revision") == expected_revision
        and status.get("health", {}).get("status") == "Healthy"
    )


def _timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)
