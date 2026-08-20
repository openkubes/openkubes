#!/usr/bin/env python3
"""Fail-closed evaluation semantics for OK-141 controlled failures."""

from __future__ import annotations

from typing import Any


APPLICATIONS = {
    "disposable-ok141-observability-core",
    "disposable-ok141-observability-alerting",
    "disposable-ok141-observability-dashboards",
}


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
) -> bool:
    """Return true only for the exact current, healthy Application set."""
    if {item.get("metadata", {}).get("name") for item in applications} != APPLICATIONS:
        return False
    for application in applications:
        status = application.get("status", {})
        if application.get("metadata", {}).get("generation") != status.get(
            "observedGeneration"
        ):
            return False
        if status.get("conditions"):
            return False
        if status.get("sync", {}).get("status") != "Synced":
            return False
        if status.get("sync", {}).get("revision") != expected_revision:
            return False
        if status.get("health", {}).get("status") != "Healthy":
            return False
    return True
