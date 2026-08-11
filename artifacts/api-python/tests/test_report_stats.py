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
from app.rendering.daily import render_html as render_daily_html
from app.rendering.daily import render_plaintext as render_daily_plaintext
from app.rendering.final_html import render_final_html

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
    stats = _load("sample_daily_stats.json")
    headline = _fallback_headline(stats)
    assert "8 new submission(s)" in headline
    assert "2 RED" in headline
    assert "Day 12" in headline

    coverage = _fallback_coverage(stats)
    assert "T1 45/100" in coverage
    assert "Coverage —" in coverage


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
    final = _load("sample_final_stats.json")

    daily_html = render_daily_html(daily)
    daily_text = render_daily_plaintext(daily)
    final_html = render_final_html(final)

    assert "Fixture Study" in daily_html
    assert "Fixture Study" in daily_text
    assert "Fixture Study" in final_html
    # Identity: same fixture yields stable non-empty output
    assert render_daily_html(daily) == daily_html
    assert render_final_html(final) == final_html
