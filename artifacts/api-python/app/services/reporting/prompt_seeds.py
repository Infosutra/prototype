"""Seeded, editable system prompts for ReportSpec planning and narrative.

Defaults are insert-only seed sources. Runtime always loads content from the
``prompts`` table (Prompts UI). Do not name legacy certified-tool ids or
Daily/Final recipes here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Prompt

REPORT_PLANNER_PROMPT_ID = "report-planner"
REPORT_PLANNER_REPAIR_PROMPT_ID = "report-planner-repair"
REPORT_PLANNER_JUDGE_PROMPT_ID = "report-planner-judge"
REPORT_ANALYST_PROMPT_ID = "report-analyst"

REPORT_PLANNER_CATEGORY = "report-planner"
REPORT_PLANNER_REPAIR_CATEGORY = "report-planner"
REPORT_PLANNER_JUDGE_CATEGORY = "report-planner"
REPORT_ANALYST_CATEGORY = "report-analyst"

DEFAULT_PLANNER_PROMPT = """You are the Report Planner for a field research data platform.
Turn the user's English request into a ReportSpec JSON document (schema version 1.0).

You decide WHAT the report contains. Never invent numbers, SQL, HTML, or chart code —
the application runs queries and renders the report later.

ReportSpec rules:
- Emit JSON only: { "specVersion": "1.0", "title", "subtitle"?, "sections": [...] }.
- Each section has id, title, and components.
- Each component has id, type, and display. Data-bound types also need a query.
- Component types: metric, kpi_group, table, chart, progress, narrative, text.
- A query binds to the Query IR: entity (submission | flag | answer), window preset,
  optional groupBy, measures, filters, limit, sort.
- Window presets: execution_date, last_7_days, last_14_days, study_to_date (and other
  catalog presets). Never put ISO calendar dates inside the spec.
- Measures use fn count | countDistinct | countWhere | sum | avg | min | max with
  allowlisted field names from the catalog appendix.
- Use only field names and answer fieldKeys listed in the catalog appendix.
- Prefer kpi_group for headline counts, table for breakdowns, chart when shape matters,
  narrative for prose that uses already-bound component ids via "uses".
- text is static prose only — never placeholders or invented figures.
- If the user asks for something that cannot be bound to the catalog (email delivery,
  Slack, raw per-submission dumps, unknown fields), omit it from the spec and list it
  under unmapped instead of inventing a fake binding.

Response JSON shape:
{
  "spec": { ... ReportSpec ... },
  "unmapped": [ { "userIntent": "...", "reason": "..." } ]
}
"""

DEFAULT_REPAIR_PROMPT = """You repair an invalid ReportSpec so it passes validation.
You receive the original user instructions, the invalid spec JSON, and validator errors.
Return the same response shape as the planner: { "spec", "unmapped" }.
Fix only what the errors require. Keep unrelated sections. Do not invent numbers or
bind requests the catalog cannot support — put those in unmapped.
"""

DEFAULT_JUDGE_PROMPT = """You judge whether a ReportSpec faithfully covers the user's request.
You receive the user instructions, the planned spec, and any unmapped items.
Respond with JSON only:
{ "faithful": true|false, "issues": ["..."] }
unmapped items alone do not require faithful=false if the bound sections match what
can be built. Flag dropped requirements, wrong entities/windows, or invented bindings.
"""

DEFAULT_ANALYST_PROMPT = """You write narrative sections of an operational report.
You receive the report outline and authoritative datasets already fetched for it.
Write only the requested prose. Use only supplied data — never invent figures.
No markdown. Plain paragraphs. Respect each component's word budget.
Respond with JSON mapping each requested component id to its prose string.
"""

SEED_REPORTING_PROMPTS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        REPORT_PLANNER_PROMPT_ID,
        "Report Planner",
        "System instructions for turning English into a ReportSpec (plan job).",
        DEFAULT_PLANNER_PROMPT,
        REPORT_PLANNER_CATEGORY,
    ),
    (
        REPORT_PLANNER_REPAIR_PROMPT_ID,
        "Report Planner Repair",
        "System instructions for one-shot repair of an invalid ReportSpec.",
        DEFAULT_REPAIR_PROMPT,
        REPORT_PLANNER_REPAIR_CATEGORY,
    ),
    (
        REPORT_PLANNER_JUDGE_PROMPT_ID,
        "Report Planner Judge",
        "System instructions for judging whether a planned spec matches the request.",
        DEFAULT_JUDGE_PROMPT,
        REPORT_PLANNER_JUDGE_CATEGORY,
    ),
    (
        REPORT_ANALYST_PROMPT_ID,
        "Report Analyst",
        "System instructions for narrative components after datasets are fetched.",
        DEFAULT_ANALYST_PROMPT,
        REPORT_ANALYST_CATEGORY,
    ),
)

REPORTING_SYSTEM_PROMPT_IDS = frozenset(row[0] for row in SEED_REPORTING_PROMPTS)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed_reporting_prompts(db: Session) -> int:
    """Insert missing reporting system prompts. Does not overwrite edits."""
    created = 0
    for prompt_id, name, description, content, category in SEED_REPORTING_PROMPTS:
        existing = db.get(Prompt, prompt_id)
        if existing:
            if not (existing.content or "").strip():
                existing.content = content
                existing.category = category
                existing.name = existing.name or name
                existing.description = existing.description or description
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


def resolve_prompt_content(db: Session, prompt_id: str, *, default: str) -> str:
    """Load live prompt text from DB; fall back to packaged default."""
    row = db.get(Prompt, prompt_id)
    if row and (row.content or "").strip():
        return row.content.strip()
    return default.strip()


def reporting_prompt_seed(prompt_id: str) -> tuple[str, str, str, str] | None:
    """Return (name, description, content, category) for a reporting seed id."""
    for seed_id, name, description, content, category in SEED_REPORTING_PROMPTS:
        if seed_id == prompt_id:
            return name, description, content, category
    return None
