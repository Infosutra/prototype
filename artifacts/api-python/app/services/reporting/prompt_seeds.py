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
- SECTION NUMBERING: When the user labels a block "Section 1.1 — …", "Section 1.4 — …",
  put that number in section.title exactly (e.g. "1.1 — Today's intake and flags by tool").
  Do not drop the number. Opening KPI/headline blocks without a Section label stay unnumbered.
- PATCH MODE: When currentSpec is provided and the user adds a new Section N.M, you MUST add
  a new section for it (or replace that numbered section). Never claim success while omitting
  a newly requested Section number. If it cannot bind to the catalog, omit it and list it under
  unmapped with the section label — do not silently skip it.
- Each component has id, type, and display (always an object, never a string).
- Data-bound types need a query (except kpi_group when each display item has its own query).
- Component types: metric, kpi_group, table, chart, progress, narrative, text.
- Window presets: execution_date, last_7_days, last_14_days, study_to_date (and other
  catalog presets). Never put ISO calendar dates inside the spec.
- Use only field names and answer fieldKeys listed in the catalog appendix.
- Prefer kpi_group for headline counts, table for breakdowns, chart when shape matters,
  narrative for prose that uses already-bound component ids via "uses".
- Charts: prefer bar_horizontal / stacked_bar / line. For category comparisons, default to
  bar_horizontal. For trends over day, line or bar_horizontal with groupBy ["day"] is fine.
  If one kind fails validation, switch kind before dropping the block — do not invent a
  rate/ratio measure (those do not exist). Use count / countWhere / flagCount / avg instead,
  or put true "rates" in unmapped.
- kpi_group glance rows: ONE QUERY PER CARD. If cards need different windows (today vs
  cumulative) or entities (submissions vs flags), put a query on each display item —
  do not share one component query. Each item query must be ungrouped (no groupBy).
- text is static prose only — never placeholders or invented figures.
- If the user asks for something that cannot be bound to the catalog (email delivery,
  Slack, raw per-submission dumps, unknown fields), omit it from the spec and list it
  under unmapped instead of inventing a fake binding.

Query IR shape (required field names — do not invent aliases):
- Every query MUST include "entity" and "window".
- groupBy: ["toolCode"] for grouping. Never emit "dimensions".
- measures[]: { "id": "total", "fn": "count"|"countDistinct"|"countWhere"|"sum"|"avg"|"min"|"max",
  "field"?: "...", "eq"?: true|false|"..." }
  Never use a "measure" key. Never put filters inside a measure.
- filters[]: { "field": "...", "op": "eq"|"neq"|"in"|"isTrue"|"isFalse"|"gt"|"gte"|"lt"|"lte",
  "value"?: ... }
  Never use "operator" — the key is "op".
- sort: { "field": "...", "dir": "asc"|"desc" }  (never "order" or "direction")
- display examples:
  kpi_group (mixed windows/entities) → {
    "items": [
      { "label": "Submissions today",
        "query": { "entity": "submission", "window": "execution_date",
                   "measures": [{ "id": "value", "fn": "count" }] } },
      { "label": "Cumulative submissions",
        "query": { "entity": "submission", "window": "study_to_date",
                   "measures": [{ "id": "value", "fn": "count" }] } }
    ]
  }
  kpi_group (same window only) → component query + { "items": [{ "label": "Total", "field": "total" }] }
  table → { "columns": ["enumerator", "total"] }
  chart → { "kind": "bar_horizontal", "x": "toolCode", "y": ["total"] }
  narrative → { "role": "insight"|"warning"|"action", "instruction": "...", "maxWords"?: 120 }
  text → { "body": "..." }

Minimal example component (mixed glance — preferred for daily intake KPIs):
{
  "id": "glance",
  "type": "kpi_group",
  "display": {
    "items": [
      {
        "label": "Submissions today",
        "query": {
          "entity": "submission",
          "window": "execution_date",
          "measures": [{ "id": "value", "fn": "count" }]
        }
      },
      {
        "label": "RED flags open",
        "query": {
          "entity": "flag",
          "window": "study_to_date",
          "measures": [
            { "id": "value", "fn": "countWhere", "field": "severity", "eq": "red" }
          ]
        }
      }
    ]
  }
}

Response JSON shape:
{
  "spec": { ... ReportSpec ... },
  "unmapped": [ { "userIntent": "...", "reason": "..."} ]
}
"""

DEFAULT_REPAIR_PROMPT = """You repair an invalid ReportSpec so it passes validation.
You receive the original user instructions, the invalid spec JSON, and validator errors.
Return the same response shape as the planner: { "spec", "unmapped" }.
Fix only what the errors require. Keep unrelated sections. Do not invent numbers or
bind requests the catalog cannot support — put those in unmapped.

Hard requirements when repairing:
- every query needs entity and window
- grouping is groupBy (never dimensions)
- kpi_group mixed windows/entities → one query per display item (no shared component query)
- measures must use keys id + fn (never "measure"); never invent rate/ratio fns
- filters must use key op (never "operator")
- sort uses dir (never "order"/"direction")
- display must be an object matching the component type
- if a chart fails, try another chart kind (bar/line/bar_horizontal) with the same query
  before removing it; otherwise convert that block to a table or list it under unmapped
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


def _packaged_prompt_stale(prompt_id: str, text: str) -> bool:
    """Refresh only the packaged planner/repair rows, not user-edited prompts."""
    if prompt_id == REPORT_PLANNER_PROMPT_ID:
        return (
            "Turn the user's English request into a ReportSpec JSON document" in text
            and (
                "ONE QUERY PER CARD" not in text
                or "SECTION NUMBERING" not in text
                or "PATCH MODE" not in text
                or "never invent a rate/ratio" not in text
                or "default to" not in text
                or "bar_horizontal" not in text
            )
        )
    if prompt_id == REPORT_PLANNER_REPAIR_PROMPT_ID:
        return (
            "You repair an invalid ReportSpec so it passes validation" in text
            and (
                "one query per display item" not in text
                or "try another chart kind" not in text
            )
        )
    return False


def seed_reporting_prompts(db: Session) -> int:
    """Insert missing reporting system prompts; refresh planner/repair when stale."""
    created = 0
    updated = 0
    for prompt_id, name, description, content, category in SEED_REPORTING_PROMPTS:
        existing = db.get(Prompt, prompt_id)
        if existing:
            if not (existing.content or "").strip():
                existing.content = content
                existing.category = category
                existing.name = existing.name or name
                existing.description = existing.description or description
                updated += 1
                continue
            # Refresh packaged planner/repair text when Query IR contract is stale.
            if _packaged_prompt_stale(prompt_id, existing.content or ""):
                existing.content = content
                existing.category = category
                existing.updated_at = _now()
                updated += 1
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
    if created or updated:
        db.commit()
    return created + updated


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
