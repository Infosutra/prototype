"""Tests for calendar dates extracted from report prompts."""

from datetime import date

from app.services.report_dates import extract_report_date


def test_extracts_month_day_with_study_year() -> None:
    assert (
        extract_report_date(
            "September 2nd submissions organized per enumerator",
            study_start=date(2026, 9, 2),
        )
        == "2026-09-02"
    )


def test_extracts_iso_date() -> None:
    assert extract_report_date("Report for 2026-09-02 by enumerator") == "2026-09-02"


def test_ignores_relative_today() -> None:
    assert extract_report_date("Show today's submissions by enumerator") is None


def test_day_month_order() -> None:
    assert (
        extract_report_date("2 September submissions", study_start=date(2026, 1, 1))
        == "2026-09-02"
    )
