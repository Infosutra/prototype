"""Template version append skips no-op saves."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import ReportTemplateVersion
from app.services.report_templates import add_version, create_draft
from app.services.reporting.prompt_seeds import seed_reporting_prompts
from tests.helpers.reporting_fixture import STUDY_ID, seed_golden_reporting

SPEC = {
    "specVersion": "1.0",
    "title": "Daily",
    "sections": [
        {
            "id": "s1",
            "title": "Intake",
            "components": [
                {
                    "id": "kpi",
                    "type": "kpi_group",
                    "query": {
                        "entity": "submission",
                        "window": "execution_date",
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"items": [{"label": "Total", "field": "total"}]},
                }
            ],
        }
    ],
}


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
    seed_reporting_prompts(db)
    return db


def test_add_version_skips_identical_spec(golden: Session) -> None:
    template = create_draft(golden, study_id=STUDY_ID, name="Draft")
    v1 = add_version(golden, template, spec=SPEC, prompt_text="first", notes="n1")
    assert v1.version == 1
    v2 = add_version(golden, template, spec=SPEC, prompt_text="again", notes="n2")
    assert v2.id == v1.id
    assert v2.version == 1
    count = golden.scalars(
        select(ReportTemplateVersion).where(
            ReportTemplateVersion.template_id == template.id
        )
    ).all()
    assert len(count) == 1


def test_add_version_bumps_when_spec_changes(golden: Session) -> None:
    template = create_draft(golden, study_id=STUDY_ID, name="Draft")
    v1 = add_version(golden, template, spec=SPEC, prompt_text="first")
    changed = {
        **SPEC,
        "title": "Weekly",
        "sections": list(SPEC["sections"]),
    }
    v2 = add_version(golden, template, spec=changed, prompt_text="second")
    assert v2.version == 2
    assert v2.id != v1.id
