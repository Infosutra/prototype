"""Tests for shared time_window resolver."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.domain.time_window import (
    TimeWindowError,
    TimeWindowInput,
    resolve_time_window,
)


def test_execution_date_preset_bounds() -> None:
    resolved = resolve_time_window(
        TimeWindowInput(preset="execution_date", execution_date="2026-09-12"),
        timezone="Asia/Kolkata",
    )
    assert resolved.from_date == date(2026, 9, 12)
    assert resolved.to_date == date(2026, 9, 12)
    assert resolved.source == "preset"
    assert resolved.timezone == "Asia/Kolkata"
    # IST midnight 2026-09-12 = 2026-09-11 18:30 UTC
    assert resolved.utc_start == datetime(2026, 9, 11, 18, 30, 0)
    # exclusive end = IST midnight 2026-09-13 = 2026-09-12 18:30 UTC
    assert resolved.utc_end == datetime(2026, 9, 12, 18, 30, 0)


def test_last_7_days_inclusive_ending_execution_date() -> None:
    resolved = resolve_time_window(
        {"preset": "last_7_days", "executionDate": "2026-09-12"},
        timezone="Asia/Kolkata",
    )
    assert resolved.from_date == date(2026, 9, 6)
    assert resolved.to_date == date(2026, 9, 12)
    assert (resolved.to_date - resolved.from_date).days + 1 == 7
    assert resolved.utc_start == datetime(2026, 9, 5, 18, 30, 0)
    assert resolved.utc_end == datetime(2026, 9, 12, 18, 30, 0)


def test_last_14_days() -> None:
    resolved = resolve_time_window(
        TimeWindowInput(preset="last_14_days", execution_date="2026-09-12"),
        timezone="Asia/Kolkata",
    )
    assert resolved.from_date == date(2026, 8, 30)
    assert resolved.to_date == date(2026, 9, 12)


def test_study_to_date_uses_study_start() -> None:
    resolved = resolve_time_window(
        TimeWindowInput(preset="study_to_date", execution_date="2026-09-12"),
        timezone="Asia/Kolkata",
        study_start_date="2026-08-01",
    )
    assert resolved.from_date == date(2026, 8, 1)
    assert resolved.to_date == date(2026, 9, 12)


def test_study_to_date_falls_back_to_execution() -> None:
    resolved = resolve_time_window(
        TimeWindowInput(preset="study_to_date", execution_date="2026-09-12"),
        timezone="Asia/Kolkata",
        study_start_date=None,
    )
    assert resolved.from_date == date(2026, 9, 12)
    assert resolved.to_date == date(2026, 9, 12)


def test_absolute_from_to_bounds() -> None:
    resolved = resolve_time_window(
        {"from": "2026-09-10", "to": "2026-09-12"},
        timezone="Asia/Kolkata",
    )
    assert resolved.from_date == date(2026, 9, 10)
    assert resolved.to_date == date(2026, 9, 12)
    assert resolved.source == "range"
    assert resolved.utc_start == datetime(2026, 9, 9, 18, 30, 0)
    assert resolved.utc_end == datetime(2026, 9, 12, 18, 30, 0)


def test_reject_from_after_to() -> None:
    with pytest.raises(TimeWindowError, match="after"):
        resolve_time_window(
            {"from": "2026-09-12", "to": "2026-09-10"},
            timezone="Asia/Kolkata",
        )


def test_range_cap_from_max_range_days() -> None:
    with pytest.raises(TimeWindowError, match="max_range_days"):
        resolve_time_window(
            {"from": "2025-01-01", "to": "2026-09-12"},
            timezone="Asia/Kolkata",
            max_range_days=366,
        )


def test_ist_day_not_equal_utc_day() -> None:
    """A timestamp just after IST midnight is still previous UTC calendar day."""
    resolved = resolve_time_window(
        TimeWindowInput(preset="execution_date", execution_date="2026-09-12"),
        timezone="Asia/Kolkata",
    )
    assert resolved.utc_start.date() == date(2026, 9, 11)
    assert resolved.from_date == date(2026, 9, 12)


def test_execution_date_defaults_to_today_in_study_tz() -> None:
    # Fixed "now" = 2026-09-12 02:00 UTC → still 2026-09-12 in Kolkata (07:30)
    now = datetime(2026, 9, 12, 2, 0, 0, tzinfo=timezone.utc)
    resolved = resolve_time_window(
        TimeWindowInput(preset="execution_date"),
        timezone="Asia/Kolkata",
        now=now,
    )
    assert resolved.from_date == date(2026, 9, 12)


def test_reject_mixed_modes() -> None:
    with pytest.raises(ValueError):
        TimeWindowInput(
            preset="execution_date",
            execution_date="2026-09-12",
            from_="2026-09-01",
            to="2026-09-12",
        )


def test_reject_incomplete_absolute() -> None:
    with pytest.raises(ValueError):
        TimeWindowInput.model_validate({"from": "2026-09-01"})


def test_utc_end_is_exclusive() -> None:
    resolved = resolve_time_window(
        {"from": "2026-09-12", "to": "2026-09-12"},
        timezone="UTC",
    )
    assert resolved.utc_start == datetime(2026, 9, 12, 0, 0, 0)
    assert resolved.utc_end == datetime(2026, 9, 13, 0, 0, 0)
    assert resolved.utc_end > resolved.utc_start
