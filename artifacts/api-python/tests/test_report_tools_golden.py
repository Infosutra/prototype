"""Golden lock-in for all registered report data sources.

Triangulation note
------------------
This suite uses ``build_daily_dqa_stats`` only. ``triangulation_summary``
therefore golden-locks to ``[]``. Real triangulation output requires seeded
``TriangulationView`` rows and ``build_final_dqa_stats`` — out of scope here.

Time
----
Uses the shared ``frozen_now`` fixture (freezegun) so ``generatedAtDisplay``
is deterministic. Do not scrub wall-clock fields.

Regenerate goldens
------------------
::

    UPDATE_REPORT_TOOL_GOLDENS=1 uv run pytest tests/test_report_tools_golden.py -q
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings
from app.domain.report_spec.context import ReportExecutionContext
from app.services.report_stats import build_daily_dqa_stats
from app.services.report_tools import ReportDataContext, all_descriptors, call_tool
from tests.fixtures.report_tools_golden.seed import (
    REPORT_DATE,
    STUDY_ID,
    TIMEZONE,
    seed_golden_study,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "report_tools_golden"
UPDATE_GOLDENS = os.environ.get("UPDATE_REPORT_TOOL_GOLDENS") == "1"


def _cases() -> list[tuple[str, str, dict[str, Any] | None]]:
    """(golden_stem, tool_id, params)."""
    cases: list[tuple[str, str, dict[str, Any] | None]] = []
    for descriptor in sorted(all_descriptors(), key=lambda d: d.id):
        if descriptor.id == "top_failing_rules":
            cases.append(("top_failing_rules__today", "top_failing_rules", {"scope": "today"}))
            cases.append(
                ("top_failing_rules__cumulative", "top_failing_rules", {"scope": "cumulative"})
            )
        else:
            cases.append((descriptor.id, descriptor.id, None))
    return cases


CASES = _cases()


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def golden_context(db: Session, frozen_now) -> ReportDataContext:
    study = seed_golden_study(db)
    settings = db.get(AppSettings, "settings")
    assert settings is not None
    stats = build_daily_dqa_stats(
        db, study, report_date=REPORT_DATE, settings=settings
    )
    ctx = ReportExecutionContext(
        report_kind="daily",
        study_id=STUDY_ID,
        execution_date=REPORT_DATE,
        timezone=TIMEZONE,
    )
    return ReportDataContext(db, ctx, settings=settings, stats=stats)


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _load_golden(stem: str) -> Any:
    path = GOLDEN_DIR / f"{stem}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize(
    "stem,tool_id,params",
    CASES,
    ids=[c[0] for c in CASES],
)
def test_report_tool_matches_golden(
    golden_context: ReportDataContext,
    stem: str,
    tool_id: str,
    params: dict[str, Any] | None,
) -> None:
    """Deep-equality lock for each registered report tool (and both top_failing_rules scopes).

    triangulation_summary is intentionally ``[]`` under this daily-only fixture.
    """
    payload = call_tool(golden_context, tool_id, params)
    if UPDATE_GOLDENS:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        (GOLDEN_DIR / f"{stem}.json").write_text(_dump(payload), encoding="utf-8")
        return

    expected = _load_golden(stem)
    assert payload == expected, f"Golden drift for {stem} ({tool_id} params={params})"
