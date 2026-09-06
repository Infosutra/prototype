"""Tests for Daily §1.5 enumerator submission detail aggregation."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.domain.reporting.daily_enumerators import (
    build_enumerator_submission_details,
    format_submission_problems,
)
from app.domain.report_spec.spec import ReportSpec, Section, TableColumn, TableComponent
from app.rendering.spec import RenderPayload, render_spec_html, render_spec_plaintext
from tests.test_report_stats import _load


def _project(pid: str, name: str, tool: str) -> SimpleNamespace:
    return SimpleNamespace(id=pid, name=name, tool_code=tool)


def _sub(
    *,
    sid: str,
    kobo_id: str,
    enumerator: str,
    project_id: str,
    submitted_at: datetime,
    uuid: str | None = None,
    form_name: str = "Form",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sid,
        kobo_id=kobo_id,
        uuid=uuid,
        enumerator=enumerator,
        project_id=project_id,
        submitted_at=submitted_at,
        form_name=form_name,
    )


def _flag(
    *,
    submission_id: str,
    rule_id: str,
    severity: str,
    title: str,
    message: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        submission_id=submission_id,
        rule_id=rule_id,
        severity=severity,
        title=title,
        message=message,
    )


def test_format_submission_problems_empty():
    assert format_submission_problems([]) == "—"


def test_format_submission_problems_lists_flags():
    text = format_submission_problems(
        [
            {
                "ruleId": "R1",
                "severity": "red",
                "title": "Missing GPS",
                "message": "GPS required",
            }
        ]
    )
    assert text == "RED R1: Missing GPS — GPS required"


def test_build_enumerator_submission_details_status_and_sort():
    projects = {
        "p1": _project("p1", "Facility", "T1"),
        "p2": _project("p2", "Teachers", "T2"),
    }
    today_subs = [
        _sub(
            sid="s-clean",
            kobo_id="100",
            enumerator="Bo",
            project_id="p2",
            submitted_at=datetime(2026, 3, 15, 10, 0, 0),
        ),
        _sub(
            sid="s-red",
            kobo_id="200",
            enumerator="Ada",
            project_id="p1",
            submitted_at=datetime(2026, 3, 15, 12, 0, 0),
            uuid="uuid-red",
        ),
        _sub(
            sid="s-amber",
            kobo_id="201",
            enumerator="Ada",
            project_id="p1",
            submitted_at=datetime(2026, 3, 15, 11, 0, 0),
        ),
    ]
    today_flags = [
        _flag(
            submission_id="s-red",
            rule_id="R1",
            severity="red",
            title="Missing GPS",
            message="GPS required",
        ),
        _flag(
            submission_id="s-amber",
            rule_id="R2",
            severity="amber",
            title="Skip residue",
            message="Unexpected",
        ),
    ]

    details = build_enumerator_submission_details(
        today_subs=today_subs,
        today_flags=today_flags,
        project_by_id=projects,
    )

    assert [d["enumerator"] for d in details] == ["Ada", "Bo"]
    ada = details[0]
    assert ada["submissionsToday"] == 2
    assert ada["redSubmissions"] == 1
    assert ada["amberSubmissions"] == 1
    # Newest first
    assert [s["koboId"] for s in ada["submissions"]] == ["200", "201"]
    assert ada["submissions"][0]["status"] == "red"
    assert ada["submissions"][0]["uuid"] == "uuid-red"
    assert ada["submissions"][0]["projectName"] == "Facility"
    assert ada["submissions"][0]["flags"][0]["ruleId"] == "R1"
    assert ada["submissions"][1]["status"] == "amber"

    bo = details[1]
    assert bo["submissionsToday"] == 1
    assert bo["submissions"][0]["status"] == "clean"
    assert bo["submissions"][0]["flags"] == []


def test_quality_table_renders_enumerator_issues_without_links():
    spec = ReportSpec(
        title="Quality",
        sections=[
            Section(
                title="1.5 Submission quality by enumerator",
                components=[
                    TableComponent(
                        id="q",
                        data_source="enumerator_submission_quality",
                        columns=[
                            TableColumn(field="enumerator", label="Enumerator"),
                            TableColumn(field="issues", label="DQA issues"),
                        ],
                    )
                ],
            )
        ],
    )
    html = render_spec_html(
        RenderPayload(
            spec=spec,
            data={
                "enumerator_submission_quality": [
                    {"enumerator": "Ada", "issues": "Missing GPS"},
                ]
            },
        )
    )
    assert "1.5 Submission quality by enumerator" in html
    assert "Ada" in html
    assert "Missing GPS" in html
    assert "<a " not in html
    text = render_spec_plaintext(
        RenderPayload(
            spec=spec,
            data={"enumerator_submission_quality": [{"enumerator": "Ada", "issues": "Missing GPS"}]},
        )
    )
    assert "Ada" in text