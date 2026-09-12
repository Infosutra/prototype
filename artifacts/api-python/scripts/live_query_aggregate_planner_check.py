"""Live Stage 3 planner checks against the report planner model from local DB.

Uses ``ai_report_planner_model`` (fallback ``ai_model``) — the same path as
``llm_report_planner_config_from_app_settings`` / report planner. Does not use
``ai_compile_model``.

Run:
  uv run python scripts/live_query_aggregate_planner_check.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db.base import Base
from app.db.models import AppSettings, Prompt
from app.domain.report_spec.validation import validate_spec
from app.integrations.llm.settings import llm_report_planner_config_from_app_settings
from app.services.report_planner import plan_spec
from app.services.report_planner_prompts import (
    DEFAULT_PLANNER_PROMPT,
    REPORT_PLANNER_CATEGORY,
    REPORT_PLANNER_PROMPT_ID,
)
from app.services.report_tools import descriptors_by_id

REAL_DB = Path("/home/sarath/work/Infosutra/Data-Insights-Hub/data/infosutra.sqlite")

CASES = [
    (
        "enumerator_perf_last_14",
        "Show enumerator performance for the last 14 days",
        {
            "prefer": "enumerator_performance_study",
            "require_source_date_window": {
                "enumerator_performance_study": "last_14_days",
            },
            "avoid": {
                "enumerator_performance_today",
                "enumerator_submission_quality",
            },
        },
    ),
    (
        "flag_by_enumerator",
        "Show flag counts grouped by enumerator instead of by tool",
        {
            "prefer": "query_aggregate",
            "avoid": {
                "findings_by_tool",
                "enumerator_performance_today",
                "enumerator_performance_study",
            },
        },
    ),
    (
        "last_two_weeks",
        "Give me submission and flag counts for the last two weeks only",
        {"prefer": "query_aggregate", "require_date_window": "last_14_days"},
    ),
    (
        "findings_by_rule",
        "Break down findings by rule across the study (not by project)",
        {"prefer_any": {"top_failing_rules", "query_aggregate"}},
    ),
    (
        "top_failing_rules_phrasing",
        "Show the top failing / most common DQA rules across the study",
        {
            "prefer": "top_failing_rules",
            "avoid": {"query_aggregate"},
        },
    ),
    (
        "amber_by_tool",
        "Flag rate by tool for amber only",
        {"prefer": "query_aggregate", "avoid_fabricated_rate": True},
    ),
    (
        "two_windows",
        "Show submission counts for the last 7 days in one table and "
        "submission counts for the last 14 days in another table. "
        "Do not include study totals or other certified KPI sources.",
        {"prefer": "query_aggregate", "require_windows": {"last_7_days", "last_14_days"}},
    ),
]


def _load_ai_settings() -> dict:
    con = sqlite3.connect(REAL_DB)
    # Prefer the dedicated planner column when present (post-migration); older DBs
    # omit it and we treat the planner model as unset → fall back to ai_model.
    cols = {row[1] for row in con.execute("PRAGMA table_info(settings)").fetchall()}
    select_cols = [
        "ai_enabled",
        "ai_api_key",
        "ai_provider",
        "ai_model",
        "ai_compile_model",
        "ai_base_url",
        "ai_temperature",
        "ai_max_tokens",
        "ai_timeout_seconds",
    ]
    has_planner = "ai_report_planner_model" in cols
    if has_planner:
        select_cols.insert(5, "ai_report_planner_model")
    row = con.execute(
        f"SELECT {', '.join(select_cols)} FROM settings WHERE id = 'singleton'"
    ).fetchone()
    con.close()
    if not row or not row[1]:
        raise SystemExit(f"No AI API key in {REAL_DB}")
    idx = 0

    def next_val():
        nonlocal idx
        val = row[idx]
        idx += 1
        return val

    result = {
        "ai_enabled": bool(next_val()),
        "ai_api_key": next_val(),
        "ai_provider": next_val() or "openrouter",
        "ai_model": next_val() or "",
        "ai_compile_model": next_val() or "",
    }
    result["ai_report_planner_model"] = (next_val() or "") if has_planner else ""
    result["ai_base_url"] = next_val() or ""
    result["ai_temperature"] = next_val()
    result["ai_max_tokens"] = next_val()
    result["ai_timeout_seconds"] = next_val()
    return result


def _session() -> tuple[Session, str]:
    """Build an in-memory session with production AI settings + current planner prompt."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = SessionLocal()
    ai = _load_ai_settings()
    settings = AppSettings(
        id="singleton",
        organization_name="Live Planner Check",
        ai_enabled=True,
        ai_api_key=ai["ai_api_key"],
        ai_provider=ai["ai_provider"],
        ai_model=ai["ai_model"],
        ai_compile_model=ai["ai_compile_model"],
        ai_report_planner_model=ai["ai_report_planner_model"],
        ai_base_url=ai["ai_base_url"],
        ai_temperature=ai["ai_temperature"] if ai["ai_temperature"] is not None else 0.3,
        ai_max_tokens=ai["ai_max_tokens"] if ai["ai_max_tokens"] is not None else 2048,
        ai_timeout_seconds=int(
            ai["ai_timeout_seconds"] if ai["ai_timeout_seconds"] is not None else 60
        ),
    )
    db.add(settings)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        Prompt(
            id=REPORT_PLANNER_PROMPT_ID,
            name="Report Planner",
            description="Live check prompt",
            content=DEFAULT_PLANNER_PROMPT,
            category=REPORT_PLANNER_CATEGORY,
            project_ids=[],
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    planner_model = llm_report_planner_config_from_app_settings(settings).model
    return db, planner_model


def _component_sources(spec) -> list[dict]:
    out = []
    for section in spec.sections:
        for component in section.components:
            if hasattr(component, "data_source"):
                out.append(
                    {
                        "type": component.type,
                        "dataSource": component.data_source,
                        "params": dict(component.params or {}),
                    }
                )
            elif hasattr(component, "data_sources"):
                out.append(
                    {
                        "type": component.type,
                        "dataSources": list(component.data_sources or []),
                    }
                )
    return out


def _assess(case_id: str, expect: dict, sources: list[dict]) -> list[str]:
    findings: list[str] = []
    ids = {s.get("dataSource") for s in sources if s.get("dataSource")}
    if "prefer" in expect and expect["prefer"] not in ids:
        findings.append(f"expected {expect['prefer']} but got {sorted(ids)}")
    if "prefer_any" in expect and not (ids & expect["prefer_any"]):
        findings.append(f"expected one of {expect['prefer_any']} but got {sorted(ids)}")
    avoid = expect.get("avoid") or set()
    bad = ids & avoid
    if bad:
        findings.append(f"chose disallowed source(s) {sorted(bad)}")
    if expect.get("require_date_window"):
        windows = {
            (s.get("params") or {}).get("dateWindow")
            for s in sources
            if s.get("dataSource") == "query_aggregate"
        }
        if expect["require_date_window"] not in windows:
            findings.append(f"missing dateWindow={expect['require_date_window']}; saw {windows}")
    if expect.get("require_source_date_window"):
        for source_id, want in expect["require_source_date_window"].items():
            matched = [
                (s.get("params") or {}).get("dateWindow")
                for s in sources
                if s.get("dataSource") == source_id
            ]
            if want not in matched:
                findings.append(
                    f"expected {source_id} dateWindow={want}; saw {matched} "
                    f"(sources={sorted(ids)})"
                )
    if expect.get("require_windows"):
        windows = {
            (s.get("params") or {}).get("dateWindow")
            for s in sources
            if s.get("dataSource") == "query_aggregate"
        }
        missing = expect["require_windows"] - windows
        if missing:
            findings.append(f"missing windows {missing}; saw {windows}")
        certified = ids - {"query_aggregate"}
        if certified:
            findings.append(f"unexpected certified sources with dual windows: {sorted(certified)}")
    if expect.get("avoid_fabricated_rate"):
        for s in sources:
            params = s.get("params") or {}
            measure = str(params.get("measure") or "")
            if "rate" in measure.lower() or params.get("measureField") == "rate":
                findings.append(f"fabricated rate measure in params={params}")
    return findings


def _case_ok(entry: dict) -> bool:
    return (
        entry.get("status") == "ok"
        and entry.get("valid") is True
        and not entry.get("findings")
    )


def main() -> int:
    db, planner_model = _session()
    catalog = descriptors_by_id()
    results = []
    print(f"Report planner model: {planner_model}", flush=True)
    try:
        for case_id, prompt, expect in CASES:
            print(f"\n=== {case_id} ===\nPROMPT: {prompt}", flush=True)
            entry = None
            for attempt in range(1, 4):
                planned = plan_spec(db, instructions=prompt, report_kind="adhoc")
                entry = {
                    "id": case_id,
                    "prompt": prompt,
                    "model": planner_model,
                    "attempt": attempt,
                    "status": planned.status,
                    "summary": planned.summary,
                    "reason": planned.reason,
                    "question": planned.question,
                    "errors": [e.model_dump(by_alias=True) for e in planned.errors],
                    "warnings": [w.model_dump(by_alias=True) for w in planned.warnings],
                }
                if planned.spec is not None:
                    entry["spec"] = planned.spec.model_dump(by_alias=True)
                    entry["components"] = _component_sources(planned.spec)
                    validation = validate_spec(planned.spec, catalog)
                    entry["valid"] = validation.valid
                    entry["validationErrors"] = [
                        e.model_dump(by_alias=True) for e in validation.errors
                    ]
                    entry["findings"] = _assess(case_id, expect, entry["components"])
                else:
                    entry["valid"] = False
                    entry["findings"] = ["no spec returned"]
                print(
                    json.dumps(
                        {
                            "attempt": attempt,
                            "status": entry["status"],
                            "valid": entry.get("valid"),
                            "summary": entry.get("summary"),
                            "components": entry.get("components"),
                            "findings": entry.get("findings"),
                            "validationErrors": entry.get("validationErrors"),
                            "errors": entry.get("errors"),
                            "question": entry.get("question"),
                            "warningCodes": [w.get("code") for w in (entry.get("warnings") or [])],
                        },
                        indent=2,
                        ensure_ascii=False,
                        default=str,
                    ),
                    flush=True,
                )
                if _case_ok(entry):
                    break
                print(f"(retry {attempt}/3 for {case_id})", flush=True)
            results.append(entry)
    finally:
        db.close()

    out_path = ROOT / "scripts" / "_live_query_aggregate_planner_results.json"
    out_path.write_text(
        json.dumps(
            {"model": planner_model, "cases": results},
            indent=2,
            ensure_ascii=False,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {out_path}", flush=True)
    print("\n=== Summary ===", flush=True)
    for r in results:
        print(
            f"{r['id']}: {'PASS' if _case_ok(r) else 'FAIL'} "
            f"status={r.get('status')} attempts={r.get('attempt')} "
            f"findings={r.get('findings')}",
            flush=True,
        )

    failed = [r for r in results if not _case_ok(r)]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
