"""Rule testing workspace — deterministic evaluation without persisting flags."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.domain.dqa.debug_trace import build_debug_trace
from app.domain.dqa.eval import eval_check
from app.domain.dqa.explain import explain_evaluation
from app.domain.dqa.operands import collect_relationship_codes
from app.domain.dqa.rule_quality import analyze_rule_quality, compute_field_null_rates
from app.domain.dqa.values import get_value, _is_blank
from app.services.dqa_relationship_resolver import build_related_context, load_study_relationships
from app.services.dqa_rule_packs import get_pack_for_project


def _classify_result(*, passes: bool, details: dict[str, Any], flag_when: str) -> str:
    would_flag = (not passes) if str(flag_when or "fail").lower() == "fail" else passes
    for key in ("left_relatedResolution", "right_relatedResolution"):
        status = str(details.get(key) or "")
        if status in {"none", "missing_key"}:
            return "not_applicable"
    if details.get("op") == "if_then" and passes and not details.get("then"):
        return "not_applicable"
    if would_flag:
        return "fail"
    return "pass"


def _field_values(data: dict[str, Any], pack: dict[str, Any], check: dict[str, Any] | None) -> dict[str, Any]:
    from app.domain.dqa.catalog import FIELD_REF_KEYS

    values: dict[str, Any] = {}
    if not isinstance(check, dict):
        return values

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for key in FIELD_REF_KEYS:
            ref = node.get(key)
            if isinstance(ref, str) and ref.strip():
                values[ref] = get_value(data, pack, ref)
            elif isinstance(ref, dict) and ref.get("type") == "related_field":
                values[f"related:{ref.get('relationship')}.{ref.get('field')}"] = None
        for child in node.get("checks") or []:
            walk(child)
        for nested in ("check", "if", "then"):
            if nested in node:
                walk(node[nested])

    walk(check)
    return values


def run_rule_test(
    db: Session,
    project_id: str,
    rule: dict[str, Any],
    *,
    submission_ids: list[str] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    pack = get_pack_for_project(db, project_id) or {}
    project = db.get(Project, project_id)
    study_id = project.study_id if project else None
    rel_map = load_study_relationships(db, study_id) if study_id else {}
    target_rows_cache: dict[str, list[Submission]] = {}
    target_pack_cache: dict[str, dict[str, Any]] = {}

    all_rows = list(
        db.scalars(select(Submission).where(Submission.project_id == project_id)).all()
    )
    if submission_ids:
        wanted = set(submission_ids)
        rows = [row for row in all_rows if row.id in wanted]
    else:
        rows = sorted(all_rows, key=lambda row: row.submitted_at or row.id, reverse=True)[
            : max(1, min(int(limit or 50), 200))
        ]

    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    flag_when = str(rule.get("flag_when") or "fail").lower()

    records: list[dict[str, Any]] = []
    counts = {"pass": 0, "fail": 0, "not_applicable": 0, "missing_data": 0}
    ambiguous_related_count = 0

    for submission in rows:
        data = submission.data if isinstance(submission.data, dict) else {}
        related = (
            build_related_context(
                db,
                current=submission,
                source_pack=pack,
                check=check,
                study_id=study_id,
                relationships=rel_map,
                target_rows_cache=target_rows_cache,
                target_pack_cache=target_pack_cache,
            )
            if study_id
            else {}
        )
        passes, details = eval_check(
            check,
            data=data,
            pack=pack,
            project_rows=all_rows,
            current=submission,
            related=related,
            study_id=study_id,
        )
        details = details if isinstance(details, dict) else {}
        if any(
            str(details.get(k) or "") == "ambiguous"
            for k in ("left_relatedResolution", "right_relatedResolution")
        ):
            ambiguous_related_count += 1

        field_values = _field_values(data, pack, check if isinstance(check, dict) else None)
        for code, res in (related or {}).items():
            if res.status == "resolved" and res.submission is not None:
                rel_field_keys = [
                    k for k in field_values if k.startswith(f"related:{code}.")
                ]
                for rk in rel_field_keys:
                    field_name = rk.split(".", 1)[-1]
                    field_values[rk] = get_value(res.data, res.pack, field_name)

        outcome = _classify_result(passes=passes, details=details, flag_when=flag_when)
        if outcome == "not_applicable" and not any(not _is_blank(v) for v in field_values.values()):
            outcome = "missing_data"
        counts[outcome] = counts.get(outcome, 0) + 1

        explanation = explain_evaluation(
            check=check if isinstance(check, dict) else None,
            details=details,
            passes=passes,
            flag_when=flag_when,
        )
        trace = build_debug_trace(
            check=check if isinstance(check, dict) else None,
            details=details,
            passes=passes,
        )
        related_refs = []
        for code, res in (related or {}).items():
            related_refs.append(
                {
                    "relationship": code,
                    "status": res.status,
                    "join_key": res.join_key,
                    "submission_id": res.submission.id if res.submission else None,
                }
            )

        records.append(
            {
                "submission_id": submission.id,
                "kobo_id": submission.kobo_id,
                "enumerator": submission.enumerator,
                "outcome": outcome,
                "would_flag": explanation.get("would_flag"),
                "field_values": field_values,
                "related": related_refs,
                "explanation": explanation,
                "debug_trace": trace,
                "details": details,
            }
        )

    field_names: set[str] = set()
    if isinstance(check, dict):
        from app.domain.dqa.catalog import FIELD_REF_KEYS

        def collect_fields(node: Any) -> None:
            if not isinstance(node, dict):
                return
            for key in FIELD_REF_KEYS:
                ref = node.get(key)
                if isinstance(ref, str) and ref.strip():
                    field_names.add(ref.strip())
            for child in node.get("checks") or []:
                collect_fields(child)
            for nested in ("check", "if", "then"):
                if nested in node:
                    collect_fields(node[nested])

        collect_fields(check)

    preview_summary = {
        "submissions_checked": len(records),
        "flag_count": counts["fail"],
        "pass_count": counts["pass"],
        "not_applicable_count": counts["not_applicable"],
        "missing_data_count": counts["missing_data"],
        "ambiguous_related_count": ambiguous_related_count,
    }
    warnings = analyze_rule_quality(
        rule,
        preview=preview_summary,
        form_field_stats=compute_field_null_rates(all_rows, pack, field_names),
    )

    return {
        **preview_summary,
        "records": records,
        "examples": records[:8],
        "warnings": warnings,
    }


def explain_flag(
    *,
    rule: dict[str, Any],
    details: dict[str, Any] | None,
    passes: bool | None = None,
) -> dict[str, Any]:
    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    if passes is None:
        flag_when = str(rule.get("flag_when") or "fail").lower()
        passes = not ((details or {}).get("error"))  # best-effort when unknown
    explanation = explain_evaluation(
        check=check if isinstance(check, dict) else None,
        details=details,
        passes=bool(passes),
        flag_when=str(rule.get("flag_when") or "fail"),
    )
    trace = build_debug_trace(
        check=check if isinstance(check, dict) else None,
        details=details if isinstance(details, dict) else {},
        passes=bool(passes),
    )
    return {"explanation": explanation, "debug_trace": trace}
