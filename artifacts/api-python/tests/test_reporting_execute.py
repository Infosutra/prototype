"""Phase 3 — execute_report against golden fixture."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Report
from app.domain.reporting.spec import ReportSpec
from app.services.reporting.execute import NARRATIVE_STUB_TEXT, execute_report
from app.services.reporting.render_pdf import render_pdf
from tests.helpers.reporting_fixture import (
    EXECUTION_DATE,
    STUDY_ID,
    seed_golden_reporting,
)

_GOLDEN = Path(__file__).parent / "fixtures" / "reporting_golden_spec.json"


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


@pytest.fixture()
def golden(db: Session) -> Session:
    seed_golden_reporting(db)
    return db


def _load_spec() -> dict:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def _by_id(result: dict, component_id: str) -> dict:
    for section in result["sections"]:
        for comp in section["components"]:
            if comp["id"] == component_id:
                return comp
    raise AssertionError(f"missing component {component_id}")


def test_execute_golden_counts(golden: Session) -> None:
    result = execute_report(
        golden,
        study_id=STUDY_ID,
        spec=_load_spec(),
        window_input={"preset": "execution_date", "executionDate": EXECUTION_DATE},
    )
    kpis = _by_id(result, "s1c1")
    assert kpis.get("error") is None
    assert kpis["data"] == {"total": 25, "clean": 20, "flagged": 5}

    table = _by_id(result, "s2c1")
    assert isinstance(table["data"], list)
    assert len(table["data"]) == 3
    by_enum = {r["enumerator"]: r for r in table["data"]}
    assert by_enum["Meena"]["total"] == 8
    assert by_enum["Ravi"]["total"] == 12
    assert by_enum["Arun"]["total"] == 5

    flags = _by_id(result, "s3c1")
    assert len(flags["data"]) == 3
    assert all(r["enumerator"] == "Arun" for r in flags["data"])

    narrative = _by_id(result, "s3c2")
    assert narrative["data"]["text"] == NARRATIVE_STUB_TEXT

    assert result["window"] == {"from": EXECUTION_DATE, "to": EXECUTION_DATE}
    assert result["artifacts"].get("pdf")

    row = golden.get(Report, result["reportId"])
    assert row is not None
    assert row.result_ref
    assert row.result_ref.startswith("data/reports/")
    assert "generated_content" not in row.__dict__ or not hasattr(row, "generated_content")


def test_bad_query_component_errors_others_ok(golden: Session) -> None:
    spec = _load_spec()
    # Break s2c1 with an unknown field
    spec["sections"][1]["components"][0]["query"]["groupBy"] = ["notAField"]
    # Bypass validate by calling internals after parse... execute validates.
    # Use a valid parse then mutate query on the model path: inject via dict that
    # still parses if we use a legal-looking but unknown catalog field — won't parse
    # through validate. Skip full validate by patching validate to no-op.
    from app.services.reporting import execute as execute_mod

    with patch.object(execute_mod, "validate_report_spec", return_value=[]):
        # Still need ReportSpec parse — unknown groupBy field is allowed on Query model
        # (catalog check is in engine / validator). Query allows any string in group_by.
        result = execute_report(
            golden,
            study_id=STUDY_ID,
            spec=spec,
            window_input={"preset": "execution_date", "executionDate": EXECUTION_DATE},
        )

    assert _by_id(result, "s1c1")["data"]["total"] == 25
    bad = _by_id(result, "s2c1")
    assert bad.get("error")
    assert "data" not in bad or bad.get("error")
    assert _by_id(result, "s3c1")["data"]  # still present


def test_pdf_from_result_without_requery(golden: Session) -> None:
    result = execute_report(
        golden,
        study_id=STUDY_ID,
        spec=_load_spec(),
        window_input={"preset": "execution_date", "executionDate": EXECUTION_DATE},
    )
    with patch(
        "app.services.reporting.query_engine.run",
        side_effect=AssertionError("must not re-query"),
    ):
        pdf = render_pdf(result)
    assert isinstance(pdf, (bytes, bytearray))
    assert len(pdf) > 100
    assert pdf[:4] == b"%PDF"


def test_absolute_from_to_same_day(golden: Session) -> None:
    result = execute_report(
        golden,
        study_id=STUDY_ID,
        spec=_load_spec(),
        window_input={"from": EXECUTION_DATE, "to": EXECUTION_DATE},
    )
    assert _by_id(result, "s1c1")["data"] == {"total": 25, "clean": 20, "flagged": 5}
    assert result["window"] == {"from": EXECUTION_DATE, "to": EXECUTION_DATE}


def test_report_spec_parses_golden() -> None:
    ReportSpec.model_validate(_load_spec())
