from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from m0a_v6_fixes import FixError, amend_admission_manifest, wait_until_not_before  # noqa: E402


AMENDMENT = ROOT / "admission-namespace-presence-amendment-v1.yaml"


def test_admission_amendment_is_exact_and_presence_guarded() -> None:
    rendered = amend_admission_manifest(AMENDMENT).decode()
    assert hashlib.sha256(rendered.encode()).hexdigest() == "c6ea2bd8459b462d0ed65f42696b11931f136565b58ff4d04e7932399dc3d4f7"
    assert rendered.count("(has(request.namespace) ? request.namespace : '') == x.namespace") == 1
    assert "request.namespace == x.namespace" not in rendered.replace("(has(request.namespace) ? request.namespace : '') == x.namespace", "")
    documents = list(yaml.safe_load_all(rendered))
    assert len(documents[0]["spec"]["validations"][0]["expression"].split("{'group':")) - 1 == 19


def test_changed_base_digest_fails_closed(tmp_path: Path) -> None:
    value = yaml.safe_load(AMENDMENT.read_text())
    value["spec"]["base"]["digest"] = "sha256:" + "0" * 64
    path = tmp_path / "amendment.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False))
    with pytest.raises(FixError, match="identity mismatch"):
        amend_admission_manifest(path)


def test_early_sleep_return_is_rechecked() -> None:
    boundary = datetime(2026, 8, 13, 7, 12, 31, tzinfo=timezone.utc)
    samples = iter([
        boundary - timedelta(seconds=2),
        boundary - timedelta(microseconds=76),
        boundary + timedelta(microseconds=1),
    ])
    sleeps: list[float] = []
    sampled = wait_until_not_before(boundary, now=lambda: next(samples), sleep=sleeps.append)
    assert sampled >= boundary
    assert sleeps == [2.0, 0.000076]


def test_naive_boundary_fails_closed() -> None:
    boundary = datetime(2026, 8, 13, 7, 12, 31)
    with pytest.raises(FixError, match="timezone-aware"):
        wait_until_not_before(boundary, now=lambda: boundary, sleep=lambda _: None)


def test_naive_clock_sample_fails_closed() -> None:
    boundary = datetime(2026, 8, 13, 7, 12, 31, tzinfo=timezone.utc)
    with pytest.raises(FixError, match="clock sample"):
        wait_until_not_before(boundary, now=lambda: boundary.replace(tzinfo=None), sleep=lambda _: None)
