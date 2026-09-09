#!/usr/bin/env python3
"""Prove that a frozen reconciler is detectable from `status` alone (§13 bound 5).

Every `evidence.*.observedAt` this Composition writes is a SOURCE event time. That makes
a stopped reconciler indistinguishable from a healthy one by inspection: its last verdict
persists verbatim, every timestamp in it is a real event, and it reads as a recent and
definite Valid forever. Measured on ok-mgmt 2026-08-19: the live `Database` XR held
ONE resourceVersion across 350s of 5s sampling -- zero status writes from a healthy
composite -- because Crossplane writes status only when it changes. So "nothing moved" and
"nobody is looking" produce identical bytes over any window that matters.

`status.observation.observedThrough` is the field that separates them, and this checker
holds the reader side of that contract: given a status, is it still proven? The decisive
case is `frozen-reconciler` below -- every dimension Valid, every observedAt recent, and
the verdict is still UNPROVEN because nobody looked recently. A checker that only asserted
the field's presence would pass on a status that says nothing.
"""

from __future__ import annotations

import argparse
import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

TESTS_DIR = Path(__file__).resolve().parent
CAPABILITY_DIR = TESTS_DIR.parent.parent
COMPOSITION_PATH = CAPABILITY_DIR / "crossplane/composition.yaml"
XRD_PATH = CAPABILITY_DIR / "crossplane/xrd.yaml"

RFC3339 = "%Y-%m-%dT%H:%M:%SZ"
ISO_DURATION = re.compile(r"^PT(?:(\d+)M)?(?:(\d+)S)?$")

# Read from `crossplane core start --help` in the running v2.3.3 pod on ok-mgmt
# (2026-08-19), not from documentation: individual resources are re-checked every
# --poll-interval=1m, and --sync-interval=1h double-checks everything. The per-resource
# poll is what drives a composite's status write, so it is the term that belongs in the
# freshness arithmetic; the hourly sweep is a backstop, not the cadence.
POLL_INTERVAL_SECONDS = 60


class FreshnessError(ValueError):
    pass


class RenderedYamlLoader(yaml.SafeLoader):
    """Keep date-time fields as strings, including deliberately invalid controls."""


RenderedYamlLoader.yaml_implicit_resolvers = {
    key: [r for r in resolvers if r[0] != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def parse_duration(value: Any, field: str) -> int:
    """Accept only the PT<n>M / PT<n>S shapes the XRD patterns allow."""
    if not isinstance(value, str):
        raise FreshnessError(f"{field} must be a string, got {type(value).__name__}")
    match = ISO_DURATION.match(value)
    if not match or value in {"PT", ""}:
        raise FreshnessError(f"{field} is not an accepted ISO-8601 duration: {value!r}")
    minutes, seconds = match.group(1), match.group(2)
    if minutes is None and seconds is None:
        raise FreshnessError(f"{field} names no quantity: {value!r}")
    return int(minutes or 0) * 60 + int(seconds or 0)


def parse_instant(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise FreshnessError(f"{field} must be a string, got {type(value).__name__}")
    try:
        parsed = datetime.strptime(value, RFC3339)
    except ValueError as exc:
        raise FreshnessError(f"{field} is not canonical RFC3339 UTC: {value!r}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def evaluate(status: dict[str, Any], at: datetime) -> tuple[bool, str]:
    """The reader-side rule. Returns (proven, reason).

    `proven` is about the OBSERVER, never about the subject: it says whether the evidence
    in this status may still be believed at time `at`. It deliberately ignores every
    dimension's state, because a stale observation invalidates a Valid exactly as much as
    it invalidates a Failed. Absence is unproven, not fine -- a status with no observation
    block at all is the pre-bound-5 shape, and it cannot support a freshness claim.
    """
    observation = status.get("observation")
    if not isinstance(observation, dict):
        return False, "ObservationAbsent"
    missing = [f for f in ("observedThrough", "quantum", "freshnessBound") if f not in observation]
    if missing:
        return False, "ObservationIncomplete"

    try:
        observed_through = parse_instant(observation["observedThrough"], "observedThrough")
        quantum = parse_duration(observation["quantum"], "quantum")
        bound = parse_duration(observation["freshnessBound"], "freshnessBound")
    except FreshnessError:
        return False, "ObservationUnparseable"

    if quantum <= 0:
        return False, "ObservationQuantumInvalid"
    # A quantum wider than the bound would let a healthy platform trip its own bound.
    if bound <= quantum:
        return False, "ObservationBoundNotWiderThanQuantum"
    # An observation instant in the future is a broken or untrusted clock, not freshness.
    if observed_through > at:
        return False, "ObservationInFuture"
    if (at - observed_through).total_seconds() > bound:
        return False, "ObservationStale"
    return True, "ObservedRecently"


def composition_constants() -> tuple[int, int]:
    """Read the declared quantum and bound from Composition SOURCE, not rendered output."""
    source = COMPOSITION_PATH.read_text()
    quantum = re.findall(r"\{\{- \$observationQuantumSeconds := (\d+) \}\}", source)
    bound = re.findall(r'\{\{- \$observationFreshnessBound := "([A-Z0-9]+)" \}\}', source)
    if len(quantum) != 1 or len(bound) != 1:
        raise FreshnessError(
            "Composition must declare exactly one $observationQuantumSeconds and one "
            f"$observationFreshnessBound; found {len(quantum)} and {len(bound)}"
        )
    return int(quantum[0]), parse_duration(bound[0], "$observationFreshnessBound")


def check_declared_bound() -> None:
    """The bound must exceed what a HEALTHY platform can lag, or it fires on itself."""
    quantum, bound = composition_constants()
    worst_case = quantum + POLL_INTERVAL_SECONDS
    if bound <= worst_case:
        raise FreshnessError(
            f"freshnessBound {bound}s must exceed quantum {quantum}s + poll interval "
            f"{POLL_INTERVAL_SECONDS}s = {worst_case}s, or a healthy platform trips it"
        )
    print(
        f"PASS declared bound: quantum={quantum}s, poll={POLL_INTERVAL_SECONDS}s, "
        f"worst-case healthy lag={worst_case}s < freshnessBound={bound}s"
    )


def check_xrd_requires_observation() -> None:
    """The schema must make all three fields mandatory once `observation` is present."""
    xrd = yaml.safe_load(XRD_PATH.read_text())
    schema = xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
    observation = schema["properties"]["status"]["properties"].get("observation")
    if observation is None:
        raise FreshnessError("XRD status schema has no `observation` property")
    required = set(observation.get("required", []))
    expected = {"observedThrough", "quantum", "freshnessBound"}
    if required != expected:
        raise FreshnessError(
            f"observation.required must be exactly {sorted(expected)}, got {sorted(required)}"
        )
    if observation["properties"]["observedThrough"].get("format") != "date-time":
        raise FreshnessError("observedThrough must declare format: date-time")
    print("PASS XRD schema: observation present and all three fields required")


def check_rendered(path: Path) -> None:
    """Assert the rendered instant is floored, never ahead, and inside its own quantum."""
    docs = [d for d in yaml.load_all(path.read_text(), Loader=RenderedYamlLoader) if d]
    composites = [d for d in docs if d.get("kind") == "Database"]
    if len(composites) != 1:
        raise FreshnessError(f"expected exactly one Database composite, got {len(composites)}")
    status = composites[0].get("status", {})
    observation = status.get("observation")
    if not isinstance(observation, dict):
        raise FreshnessError("rendered Database status carries no `observation` block")

    quantum, _ = composition_constants()
    observed_through = parse_instant(observation["observedThrough"], "observedThrough")
    declared_quantum = parse_duration(observation["quantum"], "quantum")
    if declared_quantum != quantum:
        raise FreshnessError(
            f"rendered quantum {declared_quantum}s disagrees with Composition source {quantum}s"
        )
    if int(observed_through.timestamp()) % quantum != 0:
        raise FreshnessError(
            f"observedThrough {observation['observedThrough']} is not floored to {quantum}s; "
            "an unfloored instant rewrites status on every reconcile"
        )

    now = datetime.now(timezone.utc)
    if observed_through > now:
        raise FreshnessError(f"observedThrough {observation['observedThrough']} is in the future")
    lag = (now - observed_through).total_seconds()
    # Flooring alone bounds the lag by one quantum; allow the render's own wall time on top.
    if lag > quantum + 120:
        raise FreshnessError(
            f"observedThrough lags {lag:.0f}s, more than one quantum ({quantum}s) plus slack"
        )

    proven, reason = evaluate(status, now)
    if not proven:
        raise FreshnessError(f"freshly rendered status evaluates as unproven: {reason}")
    print(f"PASS rendered observation: floored, {lag:.0f}s behind, proven ({reason})")


def valid_status(now: datetime) -> dict[str, Any]:
    """A status whose every dimension is Valid and every source event is recent."""
    recent = (now - timedelta(seconds=30)).strftime(RFC3339)
    return {
        "evidence": {
            dim: {"state": "Valid", "reason": "Whatever", "observedAt": recent}
            for dim in ("operational", "protection", "recovery", "capability")
        },
        "serviceReady": True,
        "serviceReadyReason": "ProductionEvidenceValid",
        "observation": {
            "observedThrough": (now - timedelta(seconds=60)).strftime(RFC3339),
            "quantum": "PT300S",
            "freshnessBound": "PT15M",
        },
    }


def negative_controls() -> None:
    """Each control must be REJECTED. The first one is the reason this bound exists."""
    now = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)

    def frozen_reconciler() -> dict[str, Any]:
        """Every dimension Valid, every source event recent, nobody looking for an hour.

        This is the shape the pre-bound-5 status could not distinguish from health, and
        it is why `evaluate` ignores dimension states entirely.
        """
        status = valid_status(now)
        status["observation"]["observedThrough"] = (now - timedelta(hours=1)).strftime(RFC3339)
        return status

    def observation_absent() -> dict[str, Any]:
        status = valid_status(now)
        del status["observation"]
        return status

    def field_missing() -> dict[str, Any]:
        status = valid_status(now)
        del status["observation"]["freshnessBound"]
        return status

    def in_future() -> dict[str, Any]:
        status = valid_status(now)
        status["observation"]["observedThrough"] = (now + timedelta(minutes=5)).strftime(RFC3339)
        return status

    def unparseable() -> dict[str, Any]:
        status = valid_status(now)
        status["observation"]["observedThrough"] = "2026-08-19 12:00:00"
        return status

    def bound_narrower_than_quantum() -> dict[str, Any]:
        status = valid_status(now)
        status["observation"]["quantum"] = "PT900S"
        status["observation"]["freshnessBound"] = "PT5M"
        return status

    def exactly_one_second_past_bound() -> dict[str, Any]:
        """The boundary itself, because an off-by-one here silently widens the bound."""
        status = valid_status(now)
        status["observation"]["observedThrough"] = (
            now - timedelta(minutes=15, seconds=1)
        ).strftime(RFC3339)
        return status

    controls = {
        "frozen-reconciler": (frozen_reconciler, "ObservationStale"),
        "observation-absent": (observation_absent, "ObservationAbsent"),
        "field-missing": (field_missing, "ObservationIncomplete"),
        "observed-in-future": (in_future, "ObservationInFuture"),
        "unparseable-instant": (unparseable, "ObservationUnparseable"),
        "bound-narrower-than-quantum": (
            bound_narrower_than_quantum,
            "ObservationBoundNotWiderThanQuantum",
        ),
        "one-second-past-bound": (exactly_one_second_past_bound, "ObservationStale"),
    }

    for name, (build, expected_reason) in controls.items():
        proven, reason = evaluate(build(), now)
        if proven:
            raise FreshnessError(f"NEGATIVE CONTROL FAILED: {name} was accepted as proven")
        if reason != expected_reason:
            raise FreshnessError(
                f"NEGATIVE CONTROL FAILED: {name} rejected for {reason!r}, "
                f"expected {expected_reason!r}"
            )
        print(f"NEGATIVE CONTROL PASS: {name}: {reason}")

    # The positive side of the same rule: without it, a checker that rejects everything
    # would pass every control above and still be useless.
    proven, reason = evaluate(valid_status(now), now)
    if not proven:
        raise FreshnessError(f"a fresh, complete observation was rejected: {reason}")
    print(f"PASS positive control: fresh observation accepted ({reason})")

    # And the boundary from the other side: exactly at the bound is still proven.
    at_bound = valid_status(now)
    at_bound["observation"]["observedThrough"] = (now - timedelta(minutes=15)).strftime(RFC3339)
    proven, reason = evaluate(at_bound, now)
    if not proven:
        raise FreshnessError(f"observation exactly at the bound was rejected: {reason}")
    print(f"PASS boundary: exactly at freshnessBound is still proven ({reason})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rendered", nargs="?", type=Path, help="rendered composite YAML")
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()

    try:
        if args.negative_controls:
            negative_controls()
        else:
            check_declared_bound()
            check_xrd_requires_observation()
            if args.rendered is not None:
                check_rendered(args.rendered)
            else:
                print(
                    "NOTE: no rendered composite given — the emitted instant is UNVERIFIED. "
                    "render-check passes one in."
                )
    except FreshnessError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
