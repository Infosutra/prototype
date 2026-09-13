"""Phase 2 — Query engine golden fixture and cases 1–13."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.domain.reporting.query import Filter, Measure, Query
from app.domain.time_window import resolve_time_window
from app.services.reporting.config import get_reporting_config
from app.services.reporting import query_engine as query_engine_mod
from app.services.reporting.query_engine import QueryError, run
from tests.helpers.reporting_fixture import (
    DAY,
    EXECUTION_DATE,
    OLDER_DAY,
    OTHER_STUDY,
    STUDY_ID,
    TZ,
    seed_golden_reporting,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    def _enable_fk(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _enable_fk)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _window(preset: str = "execution_date", **kwargs):
    payload = {"preset": preset, "executionDate": EXECUTION_DATE, **kwargs}
    return resolve_time_window(payload, timezone=TZ)


def _absolute(from_: str, to: str):
    return resolve_time_window({"from": from_, "to": to}, timezone=TZ)


def _seed_golden(db: Session) -> None:
    seed_golden_reporting(db)


@pytest.fixture()
def golden(db: Session) -> Session:
    _seed_golden(db)
    return db


def _submission_totals_query(**kwargs) -> Query:
    return Query(
        entity="submission",
        window="execution_date",
        measures=[
            Measure(id="total", fn="count"),
            Measure(id="clean", fn="countWhere", field="isClean", eq=True),
            Measure(id="flagged", fn="countWhere", field="isClean", eq=False),
        ],
        **kwargs,
    )


# --- Cases -----------------------------------------------------------------


def test_case1_ungrouped_counts(golden: Session) -> None:
    result = run(
        golden,
        _submission_totals_query(),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert result == {"total": 25, "clean": 20, "flagged": 5}


def test_case2_groupby_enumerator(golden: Session) -> None:
    result = run(
        golden,
        Query(
            entity="submission",
            window="execution_date",
            group_by=["enumerator"],
            measures=[
                Measure(id="total", fn="count"),
                Measure(id="clean", fn="countWhere", field="isClean", eq=True),
                Measure(id="flagged", fn="countWhere", field="isClean", eq=False),
            ],
        ),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert isinstance(result, list)
    by_enum = {r["enumerator"]: r for r in result}
    assert by_enum["Meena"] == {"enumerator": "Meena", "total": 8, "clean": 8, "flagged": 0}
    assert by_enum["Ravi"] == {"enumerator": "Ravi", "total": 12, "clean": 10, "flagged": 2}
    assert by_enum["Arun"] == {"enumerator": "Arun", "total": 5, "clean": 2, "flagged": 3}


def test_case3_flag_rows_severity_red(golden: Session) -> None:
    result = run(
        golden,
        Query(
            entity="flag",
            window="execution_date",
            filters=[Filter(field="severity", op="eq", value="red")],
            limit=50,
        ),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert isinstance(result, list)
    assert len(result) == 3
    assert all(r["enumerator"] == "Arun" for r in result)
    assert all(r["severity"] == "red" for r in result)
    assert {r["ruleTitle"] for r in result} == {
        "GPS missing",
        "GPS drift",
        "Duration short",
    }
    assert all(r.get("toolCode") == "T1" for r in result)


def test_case4_last_7_days_includes_older(golden: Session) -> None:
    day_only = run(
        golden,
        Query(entity="submission", window="execution_date", measures=[Measure(id="total", fn="count")]),
        study_id=STUDY_ID,
        window=_window("execution_date"),
    )
    week = run(
        golden,
        Query(entity="submission", window="last_7_days", measures=[Measure(id="total", fn="count")]),
        study_id=STUDY_ID,
        window=_window("last_7_days"),
    )
    assert day_only == {"total": 25}
    assert week == {"total": 26}


def test_case5_absolute_range(golden: Session) -> None:
    same_day = run(
        golden,
        _submission_totals_query(),
        study_id=STUDY_ID,
        window=_absolute(EXECUTION_DATE, EXECUTION_DATE),
    )
    assert same_day == {"total": 25, "clean": 20, "flagged": 5}

    wider = run(
        golden,
        Query(entity="submission", window="execution_date", measures=[Measure(id="total", fn="count")]),
        study_id=STUDY_ID,
        window=_absolute("2026-09-08", EXECUTION_DATE),
    )
    assert wider == {"total": 26}


def test_case6_reject_unknowns_and_groupby_max(golden: Session) -> None:
    with pytest.raises(Exception, match="submission|flag|answer"):
        Query(entity="widget", window="execution_date", measures=[Measure(id="n", fn="count")])  # type: ignore[arg-type]

    with pytest.raises(QueryError, match="Unknown field"):
        run(
            golden,
            Query(
                entity="submission",
                window="execution_date",
                measures=[Measure(id="n", fn="count")],
                filters=[Filter(field="notAField", op="eq", value=1)],
            ),
            study_id=STUDY_ID,
            window=_window(),
        )

    with pytest.raises(Exception):
        Filter(field="enumerator", op="like", value="x")  # type: ignore[arg-type]

    with pytest.raises(QueryError, match="groupBy"):
        run(
            golden,
            Query(
                entity="submission",
                window="execution_date",
                group_by=["enumerator", "day", "projectId"],
                measures=[Measure(id="n", fn="count")],
            ),
            study_id=STUDY_ID,
            window=_window(),
        )


def test_case7_reject_sql_injection_identifier(golden: Session) -> None:
    with pytest.raises(QueryError, match="Invalid identifier"):
        run(
            golden,
            Query(
                entity="submission",
                window="execution_date",
                measures=[Measure(id="n", fn="count")],
                filters=[Filter(field="enumerator; DROP", op="eq", value="x")],
            ),
            study_id=STUDY_ID,
            window=_window(),
        )


def test_case8_study_scope_no_leakage(golden: Session) -> None:
    other = run(
        golden,
        Query(entity="submission", window="execution_date", measures=[Measure(id="total", fn="count")]),
        study_id=OTHER_STUDY,
        window=_window(),
    )
    assert other == {"total": 1}

    empty = run(
        golden,
        Query(entity="submission", window="execution_date", measures=[Measure(id="total", fn="count")]),
        study_id="study-missing",
        window=_window(),
    )
    assert empty == {"total": 0}

    # Orphan never counted in golden study
    golden_total = run(
        golden,
        Query(entity="submission", window="execution_date", measures=[Measure(id="total", fn="count")]),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert golden_total == {"total": 25}


def test_case9_limit_honored(golden: Session) -> None:
    result = run(
        golden,
        Query(
            entity="submission",
            window="execution_date",
            group_by=["enumerator"],
            measures=[Measure(id="total", fn="count")],
            limit=2,
        ),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert isinstance(result, list)
    assert len(result) == 2


def test_case10_no_legacy_imports() -> None:
    src = Path(query_engine_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imported.add(mod)
            for alias in node.names:
                imported.add(f"{mod}.{alias.name}" if mod else alias.name)
    blob = " ".join(sorted(imported)) + "\n" + src
    assert "build_daily_dqa_stats" not in blob
    assert "entity_rows" not in blob
    assert "call_tool" not in blob
    assert "report_tools" not in blob


def test_case11_no_json_extract_in_engine() -> None:
    src = Path(query_engine_mod.__file__).read_text(encoding="utf-8")
    assert "json_extract" not in src.lower()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "data":
            pytest.fail("query_engine must not reference .data for aggregates")
        if isinstance(node, ast.Call):
            func = node.func
            name = ""
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name.lower() == "json_extract":
                pytest.fail("query_engine must not call json_extract")


def test_case12_groupby_day_uses_calendar_day(golden: Session) -> None:
    result = run(
        golden,
        Query(
            entity="submission",
            window="last_7_days",
            group_by=["day"],
            measures=[Measure(id="total", fn="count")],
        ),
        study_id=STUDY_ID,
        window=_window("last_7_days"),
    )
    assert isinstance(result, list)
    by_day = {r["day"]: r["total"] for r in result}
    assert by_day[OLDER_DAY.isoformat()] == 1
    assert by_day[DAY.isoformat()] == 25


def test_case13_optional_target_count(golden: Session) -> None:
    result = run(
        golden,
        Query(
            entity="submission",
            window="execution_date",
            group_by=["toolCode"],
            measures=[
                Measure(id="total", fn="count"),
                Measure(id="target", fn="max", field="targetCount"),
            ],
        ),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["toolCode"] == "T1"
    assert result[0]["total"] == 25
    assert result[0]["target"] == 100


def test_query_limit_max_override_allows_higher_clamp(golden: Session) -> None:
    cfg = get_reporting_config(overrides={"query_limit_max": 2, "query_limit_default": 2})
    # Without override max is 500; with max=2, limit=50 should clamp to 2
    result = run(
        golden,
        Query(
            entity="flag",
            window="execution_date",
            filters=[Filter(field="severity", op="eq", value="red")],
            limit=50,
        ),
        study_id=STUDY_ID,
        window=_window(),
        config=cfg,
    )
    assert isinstance(result, list)
    assert len(result) == 2

    # Raising max allows more rows
    cfg_hi = get_reporting_config(overrides={"query_limit_max": 500})
    result_hi = run(
        golden,
        Query(
            entity="flag",
            window="execution_date",
            filters=[Filter(field="severity", op="eq", value="red")],
            limit=50,
        ),
        study_id=STUDY_ID,
        window=_window(),
        config=cfg_hi,
    )
    assert len(result_hi) == 3


def test_answer_aggregate_requires_field_key(golden: Session) -> None:
    with pytest.raises(QueryError, match="fieldKey"):
        run(
            golden,
            Query(
                entity="answer",
                window="execution_date",
                measures=[Measure(id="n", fn="count")],
            ),
            study_id=STUDY_ID,
            window=_window(),
        )

    ok = run(
        golden,
        Query(
            entity="answer",
            window="execution_date",
            filters=[Filter(field="fieldKey", op="eq", value="q_age")],
            measures=[
                Measure(id="n", fn="count"),
                Measure(id="avgAge", fn="avg", field="valueNumber"),
            ],
        ),
        study_id=STUDY_ID,
        window=_window(),
    )
    assert ok["n"] == 1
    assert ok["avgAge"] == 32.0


def test_unknown_filter_op_rejected_at_model() -> None:
    with pytest.raises(Exception):
        Query(
            entity="submission",
            window="execution_date",
            filters=[Filter(field="enumerator", op="regex", value="x")],  # type: ignore[arg-type]
            measures=[Measure(id="n", fn="count")],
        )
