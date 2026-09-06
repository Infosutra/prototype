"""Tests for Daily / Final DQA report prompt seeding and resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import AppSettings, Prompt, Study
from app.services.dqa_daily_narratives import generate_ai_narratives
from app.services.dqa_report_prompts import (
    DAILY_DQA_CATEGORY,
    DAILY_DQA_PROMPT_ID,
    DEFAULT_DAILY_DQA_PROMPT,
    FINAL_DQA_PROMPT_ID,
    apply_output_contract,
    resolve_report_prompt,
    seed_dqa_report_prompts,
)


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


def test_seed_dqa_report_prompts_creates_defaults(db: Session):
    assert seed_dqa_report_prompts(db) == 2
    assert seed_dqa_report_prompts(db) == 0
    daily = db.get(Prompt, DAILY_DQA_PROMPT_ID)
    final = db.get(Prompt, FINAL_DQA_PROMPT_ID)
    assert daily is not None and "field data quality analyst" in daily.content
    assert final is not None and "Final DQA close-out" in final.content
    assert daily.category == DAILY_DQA_CATEGORY


def test_resolve_falls_back_to_seeded_default(db: Session):
    seed_dqa_report_prompts(db)
    study = Study(
        id="s1",
        name="Study",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study)
    db.commit()

    content, prompt_id, name = resolve_report_prompt(db, study, "daily")
    assert prompt_id == DAILY_DQA_PROMPT_ID
    assert name == "Daily DQA"
    assert "two paragraphs" in content


def test_resolve_uses_study_assigned_prompt(db: Session):
    seed_dqa_report_prompts(db)
    dedicated = Prompt(
        id="prompt-custom",
        name="Health study Daily",
        description="",
        content="You write daily DQA notes for a health survey.",
        category=DAILY_DQA_CATEGORY,
        project_ids=[],
    )
    study = Study(
        id="s1",
        name="Health",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
        daily_dqa_prompt_id="prompt-custom",
    )
    db.add_all([dedicated, study])
    db.commit()

    content, prompt_id, name = resolve_report_prompt(db, study, "daily")
    assert prompt_id == "prompt-custom"
    assert name == "Health study Daily"
    assert "health survey" in content


def test_shared_prompt_serves_multiple_studies(db: Session):
    seed_dqa_report_prompts(db)
    shared = Prompt(
        id="prompt-shared",
        name="Shared Daily",
        description="",
        content="Shared daily narrative instructions.",
        category=DAILY_DQA_CATEGORY,
        project_ids=[],
    )
    a = Study(
        id="s-a",
        name="A",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
        daily_dqa_prompt_id="prompt-shared",
    )
    b = Study(
        id="s-b",
        name="B",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
        daily_dqa_prompt_id="prompt-shared",
    )
    db.add_all([shared, a, b])
    db.commit()

    content_a, id_a, _ = resolve_report_prompt(db, a, "daily")
    content_b, id_b, _ = resolve_report_prompt(db, b, "daily")
    assert id_a == id_b == "prompt-shared"
    assert content_a == content_b


def test_apply_output_contract_appends_when_missing():
    text = apply_output_contract("daily", "Custom tone for a health study.")
    assert "Custom tone for a health study." in text
    assert "Output contract (always enforce)" in text
    # Idempotent
    assert apply_output_contract("daily", text) == text


def test_generate_ai_narratives_uses_system_prompt(db: Session):
    settings = AppSettings(id="singleton", ai_enabled=True, ai_api_key="sk-test")
    db.add(settings)
    db.commit()
    stats = {
        "studyName": "S",
        "dayNumber": 1,
        "reportDate": "2026-09-01",
        "totals": {"newToday": 1, "redToday": 0, "amberToday": 0},
        "tools": [],
        "topRulesToday": [],
        "redGrouped": [],
        "enumerators": [],
        "flagRateByDay": [],
    }

    with patch(
        "app.services.dqa_daily_narratives.chat_completion",
        return_value="Headline para.\n\nCoverage para.",
    ) as mock_chat:
        out = generate_ai_narratives(
            stats,
            settings,
            system_prompt="You write daily notes for a health survey.",
        )

    assert out["aiHeadline"] == "Headline para."
    assert out["aiCoverageNote"] == "Coverage para."
    messages = mock_chat.call_args.args[1]
    assert "health survey" in messages[0]["content"]
    assert "Output contract" in messages[0]["content"]
    assert DEFAULT_DAILY_DQA_PROMPT not in messages[0]["content"] or "health survey" in messages[0]["content"]
