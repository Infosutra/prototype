"""Report stats / narrative helpers against Phase 5 fixture snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.domain.reporting.final_stats import (
    _exhaustive_executive_summary,
    _pass_rate,
    _tr1_summary,
    enrich_final_checklist,
)
from app.domain.reporting.narratives import _fallback_coverage, _fallback_headline
from app.domain.report_spec.spec import MetricComponent, ReportSpec, Section
from app.rendering.spec import RenderPayload, render_spec_html, render_spec_plaintext

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name: str) -> dict[str, Any]:
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_pass_rate_from_final_fixture():
    stats = _load("sample_final_stats.json")
    pct, clean, flagged = _pass_rate(stats)
    # cumulative=120, flaggedSubmissions T1+T2 = 8+10 = 18
    assert flagged == 18
    assert clean == 102
    assert pct == 85.0


def test_tr1_summary_from_final_fixture():
    stats = _load("sample_final_stats.json")
    summary = _tr1_summary(stats)
    assert summary["viewId"] == "TR-1"
    assert summary["concordance"] == 82.0  # mean of 70 and 95
    assert len(summary["practices"]) == 2
    assert summary["widest"][0]["id"] == "p_handwash"


def test_fallback_headline_and_coverage_from_daily_fixture():
    """Substring smoke (kept); full strings locked in test_fallback_prose_baseline_byte_identical."""
    stats = _load("sample_daily_stats.json")
    headline = _fallback_headline(stats)
    assert "8 new submission(s)" in headline
    assert "2 RED" in headline
    assert "Day 12" in headline

    coverage = _fallback_coverage(stats)
    assert "T1 45/100" in coverage
    assert "Coverage —" in coverage


# Locked BEFORE Phase 3 fallback migration — prove byte-identical prose, not "looks similar".
EXPECTED_FALLBACK_HEADLINE = (
    "Day 12: 8 new submission(s), 2 RED to back-check tomorrow. "
    "AMBER is led by R2 (Skip residue, 3 today)."
)
EXPECTED_FALLBACK_COVERAGE = (
    "Coverage — T1 45/100 (45.0%); T2 75/80 (93.8%). "
    "T1 lags at 45.0% of plan and needs attention. "
    "Cumulative flag rate moved from 10.0% (D1) to 15.0% (D12). "
    "Action for tomorrow: complete the 2 RED back-check(s) and verify leading "
    "AMBER patterns before the next sync."
)


def test_fallback_prose_baseline_byte_identical():
    """Safety net for Phase 3: exact fallback prose from sample_daily_stats.json."""
    stats = _load("sample_daily_stats.json")
    assert _fallback_headline(stats) == EXPECTED_FALLBACK_HEADLINE
    assert _fallback_coverage(stats) == EXPECTED_FALLBACK_COVERAGE


def test_fallback_prose_from_tool_shaped_data_matches_stats_path():
    """NEW path (tool outputs → adapter) must be byte-identical to OLD stats path."""
    from app.domain.reporting.narratives import fallback_stats_from_resolved_data

    stats = _load("sample_daily_stats.json")
    tool_data = {
        "study_metadata": {"dayNumber": stats["dayNumber"]},
        "study_totals": {
            "newToday": stats["totals"]["newToday"],
            "redToday": stats["totals"]["redToday"],
            "cumulative": stats["totals"]["cumulative"],
            "amberToday": stats["totals"]["amberToday"],
            "redOpen": stats["totals"]["redOpen"],
            "amberOpen": stats["totals"]["amberOpen"],
        },
        "tool_coverage": stats["tools"],
        "top_failing_rules": stats["topRulesToday"],
        "flag_rate_trend": stats["flagRateByDay"],
    }
    view = fallback_stats_from_resolved_data(tool_data)
    assert view is not None
    assert _fallback_headline(view) == _fallback_headline(stats) == EXPECTED_FALLBACK_HEADLINE
    assert _fallback_coverage(view) == _fallback_coverage(stats) == EXPECTED_FALLBACK_COVERAGE


def test_enrich_final_checklist_appends_triangulation():
    stats = _load("sample_final_stats.json")
    # Use a checklist without the fixture's already-merged TR rows
    base = [
        {
            "severity": "red",
            "label": "Correct/back-check R1 — Missing GPS",
            "detail": "2 record(s)",
            "ownerHint": "Field supervisor",
        }
    ]
    tri = {
        "TR-9": {
            "title": "Extra view",
            "mismatchCount": 3,
        }
    }
    out = enrich_final_checklist(base, tri)
    assert len(out) == 2
    assert out[1]["label"] == "TR-9 — Extra view"
    assert out[1]["records"] == 3
    assert out[0]["owner"] == "Field supervisor"


def test_executive_summary_mentions_study_totals():
    stats = _load("sample_final_stats.json")
    prose = _exhaustive_executive_summary(stats)
    assert "120" in prose
    assert isinstance(prose, str)
    assert len(prose) > 40


def test_render_identity_smoke_daily_and_final():
    daily = _load("sample_daily_stats.json")
    spec = ReportSpec(
        title=f"DQA Daily — {daily['studyName']}",
        sections=[
            Section(
                title="Totals",
                components=[
                    MetricComponent(
                        id="t",
                        label="Cumulative",
                        data_source="study_totals",
                        field="cumulative",
                        format="int",
                    )
                ],
            )
        ],
    )
    payload = RenderPayload(
        spec=spec,
        data={"study_totals": daily["totals"]},
        meta={"organizationName": daily["organizationName"], "rows": []},
    )
    html = render_spec_html(payload)
    text = render_spec_plaintext(payload)
    assert daily["studyName"] in html
    assert "120" in text
    assert render_spec_html(payload) == html
