"""Timezone handling for report timestamps (naive-UTC bug guard)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.routers.reports import _iso_utc


def test_iso_utc_none():
    assert _iso_utc(None) is None


def test_iso_utc_naive_treated_as_utc():
    """Naive datetimes from SQLite must be treated as UTC, not local wall time."""
    naive = datetime(2026, 3, 15, 12, 0, 0)
    assert _iso_utc(naive) == "2026-03-15T12:00:00Z"


def test_iso_utc_aware_converted_to_utc_z():
    ist = timezone(timedelta(hours=5, minutes=30))
    aware = datetime(2026, 3, 15, 17, 30, 0, tzinfo=ist)
    assert _iso_utc(aware) == "2026-03-15T12:00:00Z"


def test_iso_utc_already_utc_z():
    aware = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert _iso_utc(aware) == "2026-03-15T12:00:00Z"


def test_iso_utc_does_not_shift_naive_by_local_offset():
    """
    Regression: attaching local tz then converting to UTC would shift the clock.
    Naive 12:00 must stay 12:00Z, not become 06:30Z (IST) or similar.
    """
    naive = datetime(2026, 8, 1, 12, 0, 0)
    out = _iso_utc(naive)
    assert out is not None
    assert out.endswith("Z")
    assert out.startswith("2026-08-01T12:00:00")
