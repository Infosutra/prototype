"""Seeded, editable prompts for Daily / Final DQA report narratives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.db.models import Prompt, Study
from app.services.dqa_compile_prompt import (
    DEFAULT_DQA_COMPILE_PROMPT,
    DQA_COMPILE_CATEGORY,
    DQA_COMPILE_PROMPT_ID,
)
from app.services.report_analyst import REPORT_ANALYST_PROMPT_ID
from app.services.report_planner_prompts import REPORT_PLANNER_PROMPT_ID, SEED_AI_PROMPTS

ReportKind = Literal["daily", "final"]

DAILY_DQA_CATEGORY = "daily-dqa"
FINAL_DQA_CATEGORY = "final-dqa"
DAILY_DQA_PROMPT_ID = "seed-dqa-daily"
FINAL_DQA_PROMPT_ID = "seed-dqa-final"

DEFAULT_DAILY_DQA_PROMPT = """You are a field data quality analyst for an NGO education baseline study.
Write concise, factual prose for a daily DQA email used to drive same-day back-checks.
No markdown. No speculation beyond the numbers.
Respond with exactly two paragraphs separated by a blank line:
(1) Today's headline — 1–3 sentences naming new submissions, RED count to back-check tomorrow,
and the leading AMBER theme by tool;
(2) Coverage & trend — coverage vs plan (call out any lagging tool), how the cumulative flag rate
has moved across study days, and the concrete action for tomorrow."""

DEFAULT_FINAL_DQA_PROMPT = """You write Final DQA close-out reports for NGO education baseline studies.
This document is submitted to clients for dataset sign-off.
Write an EXHAUSTIVE executive summary in 3–5 short paragraphs (blank-line separated).
No markdown. Cover: (1) analysis-readiness verdict and pass rate;
(2) RED/AMBER volumes, where they concentrate (tools + enumerators), leading rules;
(3) whether flag rates improved across the collection window;
(4) coverage vs plan by tool;
(5) the main triangulation finding (TR-1 say–do concordance and widest gaps) plus TR-3/TR-5 if relevant.
Stay factual; use only the JSON. Tone matches a concluding client brief."""

# Always appended so report parsing stays reliable if the editable Prompt row is stale.
DAILY_OUTPUT_CONTRACT = """Output contract (always enforce):
- No markdown and no speculation beyond the numbers.
- Respond with exactly two paragraphs separated by a blank line.
- Paragraph 1: today's headline (new submissions, RED count to back-check, leading AMBER theme).
- Paragraph 2: coverage vs plan, flag-rate trend, and the concrete action for tomorrow."""

FINAL_OUTPUT_CONTRACT = """Output contract (always enforce):
- No markdown.
- Write 3–5 short paragraphs separated by blank lines.
- Stay factual; use only the JSON payload.
- Cover analysis-readiness, RED/AMBER concentration, flag-rate trend, coverage vs plan, and triangulation."""

SEED_REPORT_PROMPTS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        DAILY_DQA_PROMPT_ID,
        "Daily DQA",
        "System instructions for Daily DQA headlines and coverage notes. Studies with no prompt assigned use this default.",
        DEFAULT_DAILY_DQA_PROMPT,
        DAILY_DQA_CATEGORY,
    ),
    (
        FINAL_DQA_PROMPT_ID,
        "Final DQA",
        "System instructions for Final DQA executive summaries. Studies with no prompt assigned use this default.",
        DEFAULT_FINAL_DQA_PROMPT,
        FINAL_DQA_CATEGORY,
    ),
)

SYSTEM_PROMPT_IDS = frozenset(
    {
        DAILY_DQA_PROMPT_ID,
        FINAL_DQA_PROMPT_ID,
        DQA_COMPILE_PROMPT_ID,
        REPORT_PLANNER_PROMPT_ID,
        REPORT_ANALYST_PROMPT_ID,
    }
)


def system_prompt_seed(prompt_id: str) -> tuple[str, str, str, str] | None:
    """Return (name, description, content, category) for a seeded system prompt."""
    for seed_id, name, description, content, category in SEED_REPORT_PROMPTS:
        if seed_id == prompt_id:
            return name, description, content, category
    for seed_id, name, description, content, category in SEED_AI_PROMPTS:
        if seed_id == prompt_id:
            return name, description, content, category
    if prompt_id == DQA_COMPILE_PROMPT_ID:
        return (
            "DQA rule compiler",
            "System instructions for compiling English DQA rules to JSON checks",
            DEFAULT_DQA_COMPILE_PROMPT,
            DQA_COMPILE_CATEGORY,
        )
    return None


def revert_system_prompt(db: Session, prompt_id: str) -> Prompt:
    """Restore a seeded system prompt to its packaged DEFAULT content."""
    seed = system_prompt_seed(prompt_id)
    if seed is None or prompt_id not in SYSTEM_PROMPT_IDS:
        raise ValueError("Only seeded system prompts can be reverted to the original version.")
    name, description, content, category = seed
    row = db.get(Prompt, prompt_id)
    now = _now()
    if row is None:
        row = Prompt(
            id=prompt_id,
            name=name,
            description=description,
            content=content,
            category=category,
            project_ids=[],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.name = name
        row.description = description
        row.content = content
        row.category = category
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_dqa_report_prompts(db: Session) -> int:
    """Insert missing Daily / Final DQA prompt templates. Does not overwrite edits."""
    created = 0
    for prompt_id, name, description, content, category in SEED_REPORT_PROMPTS:
        existing = db.get(Prompt, prompt_id)
        if existing:
            if not (existing.content or "").strip():
                existing.content = content
                existing.category = category
            continue
        db.add(
            Prompt(
                id=prompt_id,
                name=name,
                description=description,
                content=content,
                category=category,
                project_ids=[],
                created_at=_now(),
                updated_at=_now(),
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def apply_output_contract(kind: ReportKind, system_prompt: str) -> str:
    contract = DAILY_OUTPUT_CONTRACT if kind == "daily" else FINAL_OUTPUT_CONTRACT
    text = (system_prompt or "").strip()
    if contract.strip() not in text:
        return f"{text}\n\n{contract}".strip()
    return text


def resolve_report_prompt(
    db: Session,
    study: Study | None,
    kind: ReportKind,
) -> tuple[str, str | None, str]:
    """Return (content, prompt_id, name) for a study's Daily or Final DQA narrative.

    Assigned study prompt wins; otherwise the seeded default; otherwise the in-code default.
    """
    assigned_id = None
    if study is not None:
        assigned_id = (
            study.daily_dqa_prompt_id if kind == "daily" else study.final_dqa_prompt_id
        )
    seed_id = DAILY_DQA_PROMPT_ID if kind == "daily" else FINAL_DQA_PROMPT_ID
    default_content = DEFAULT_DAILY_DQA_PROMPT if kind == "daily" else DEFAULT_FINAL_DQA_PROMPT
    default_name = "Daily DQA" if kind == "daily" else "Final DQA"

    for prompt_id in (assigned_id, seed_id):
        if not prompt_id:
            continue
        row = db.get(Prompt, prompt_id)
        if row and (row.content or "").strip():
            return row.content.strip(), row.id, row.name
    return default_content, None, default_name
