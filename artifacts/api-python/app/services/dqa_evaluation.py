"""DQA evaluation orchestration and flag persistence."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, Submission
from app.domain.dqa.eval import eval_check
from app.domain.dqa.evaluation_metrics import EvaluationMetrics
from app.domain.dqa.highlights import resolve_highlight_fields
from app.services.dqa_relationship_resolver import (
    build_related_context,
    load_study_relationships,
    source_projects_for_target,
)
from app.domain.dqa.rule_management import active_rules
from app.services.dqa_rule_packs import get_pack_for_project, get_pack_version

logger = structlog.stdlib.get_logger(__name__)

DQA_FLAG_NAMESPACE = uuid.UUID("a3f7c2e1-4b5d-4e6f-9a0b-1c2d3e4f5a6b")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stable_flag_id(submission_id: str, rule_id: str) -> str:
    """Deterministic flag id for idempotent re-evaluation."""
    return str(uuid.uuid5(DQA_FLAG_NAMESPACE, f"{submission_id}:{rule_id}"))


def evaluate_rule(
    rule: dict[str, Any],
    *,
    data: dict[str, Any],
    pack: dict[str, Any],
    project_rows: list[Submission] | None,
    current: Submission,
    related: dict | None = None,
    study_id: str | None = None,
    pack_version: int | None = None,
    metrics: EvaluationMetrics | None = None,
) -> DqaFlag | None:
    rule_id = str(rule.get("id") or "unknown")
    started = time.perf_counter()
    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    try:
        ok, details = eval_check(
            check,
            data=data,
            pack=pack,
            project_rows=project_rows,
            current=current,
            related=related,
            study_id=study_id,
        )
    except Exception as exc:
        logger.exception(
            "dqa_rule_evaluation_failed",
            submission_id=current.id,
            rule_id=rule_id,
        )
        if metrics is not None:
            metrics.evaluation_errors.append(f"{rule_id}: {exc}")
        return None
    finally:
        if metrics is not None:
            metrics.rules_evaluated += 1
            metrics.rule_timings_ms[rule_id] = metrics.rule_timings_ms.get(rule_id, 0.0) + (
                (time.perf_counter() - started) * 1000.0
            )

    flag_when = str(rule.get("flag_when") or "fail").lower()
    should_flag = (not ok) if flag_when == "fail" else ok
    if not should_flag:
        return None
    submission_data = data if isinstance(data, dict) else {}
    highlight = resolve_highlight_fields(
        pack=pack, check=check, details=details, data=submission_data
    )
    enriched = dict(details or {})
    if highlight:
        enriched["highlightFields"] = highlight
    enriched["provenance"] = {
        "pack_version": pack_version,
        "rule_id": rule_id,
        "evaluated_at": _now().isoformat(),
        "submission_id": current.id,
    }
    if related:
        enriched["provenance"]["related_resolutions"] = {
            code: res.status for code, res in related.items()
        }
    flag = DqaFlag(
        id=stable_flag_id(current.id, rule_id),
        submission_id=current.id,
        project_id=current.project_id,
        study_id=study_id,
        rule_id=rule_id,
        severity=str(rule.get("severity") or "amber").lower(),
        title=str(rule.get("title") or rule.get("id") or "Flag"),
        message=str(rule.get("message") or rule.get("title") or "Rule failed"),
        details=enriched,
        evaluated_at=_now(),
    )
    if metrics is not None:
        metrics.flags_produced += 1
    return flag


def evaluate_submission(
    db: Session,
    submission: Submission,
    *,
    pack: dict[str, Any] | None = None,
    project_rows: list[Submission] | None = None,
    commit: bool = True,
    study_id: str | None = None,
    rel_map: dict | None = None,
    target_rows_cache: dict[str, list[Submission]] | None = None,
    target_pack_cache: dict[str, dict[str, Any]] | None = None,
    pack_version: int | None = None,
    metrics: EvaluationMetrics | None = None,
) -> list[DqaFlag]:
    from app.services.reporting.quality import upsert_quality_for_submission

    pack = pack or get_pack_for_project(db, submission.project_id)
    db.execute(delete(DqaFlag).where(DqaFlag.submission_id == submission.id))

    if study_id is None:
        project = db.get(Project, submission.project_id)
        study_id = project.study_id if project else None
        if study_id is None and submission.study_id:
            study_id = submission.study_id

    if not pack:
        upsert_quality_for_submission(
            db,
            submission.id,
            project_id=submission.project_id,
            study_id=study_id,
        )
        if commit:
            db.commit()
        return []

    if study_id and rel_map is None:
        rel_map = load_study_relationships(db, study_id)
    target_rows_cache = target_rows_cache or {}
    target_pack_cache = target_pack_cache or {}

    data = submission.data if isinstance(submission.data, dict) else {}
    flags: list[DqaFlag] = []
    for rule in active_rules(pack.get("rules") or []):
        check = rule.get("check")
        if check is None and rule.get("checks"):
            check = {"op": "all", "checks": rule["checks"]}
        related = {}
        if study_id:
            rel_started = time.perf_counter()
            related = build_related_context(
                db,
                current=submission,
                source_pack=pack,
                check=check,
                study_id=study_id,
                relationships=rel_map,
                target_rows_cache=target_rows_cache,
                target_pack_cache=target_pack_cache,
            )
            if metrics is not None:
                metrics.relationship_lookups += 1
                metrics.relationship_lookup_ms += (time.perf_counter() - rel_started) * 1000.0
        flag = evaluate_rule(
            rule,
            data=data,
            pack=pack,
            project_rows=project_rows,
            current=submission,
            related=related,
            study_id=study_id,
            pack_version=pack_version,
            metrics=metrics,
        )
        if flag:
            flags.append(flag)
            db.add(flag)

    has_red = any(f.severity == "red" for f in flags)
    if has_red:
        submission.status = "flagged"
    elif submission.status == "flagged":
        submission.status = "validated"

    # Flush flags so quality rollup can count them before commit.
    db.flush()
    upsert_quality_for_submission(
        db,
        submission.id,
        project_id=submission.project_id,
        study_id=study_id,
    )

    if commit:
        db.commit()
    return flags


def evaluate_project(
    db: Session,
    project_id: str,
    *,
    metrics: EvaluationMetrics | None = None,
    submission_ids: set[str] | list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate DQA rules for a project.

    When ``submission_ids`` is provided, only those submissions are re-evaluated
    (still using all project rows as ``project_rows`` context). An empty set
    skips work. ``None`` evaluates every local submission.
    """
    started = time.perf_counter()
    local_metrics = metrics or EvaluationMetrics()
    pack = get_pack_for_project(db, project_id)
    pack_version = get_pack_version(db, project_id) or (pack or {}).get("pack_version")
    local_metrics.pack_version = int(pack_version) if pack_version else None
    project = db.get(Project, project_id)
    study_id = project.study_id if project else None
    rel_map = load_study_relationships(db, study_id) if study_id else {}
    target_rows_cache: dict[str, list[Submission]] = {}
    target_pack_cache: dict[str, dict[str, Any]] = {}
    rows = list(
        db.scalars(
            select(Submission).where(Submission.project_id == project_id)
        ).all()
    )
    if submission_ids is not None:
        wanted = set(submission_ids)
        if not wanted:
            local_metrics.submissions = 0
            local_metrics.flagged_submissions = 0
            local_metrics.duration_ms = (time.perf_counter() - started) * 1000.0
            logger.info(
                "dqa_evaluate",
                project_id=project_id,
                submissions=0,
                flags=0,
                duration_ms=round(local_metrics.duration_ms, 1),
                errors=0,
                skipped="empty",
            )
            return {
                "submissions": 0,
                "flagged_submissions": 0,
                "flags": 0,
                "metrics": local_metrics.to_dict(),
            }
        targets = [row for row in rows if row.id in wanted]
    else:
        targets = rows

    flagged_submissions = 0
    for submission in targets:
        try:
            flags = evaluate_submission(
                db,
                submission,
                pack=pack,
                project_rows=rows,
                commit=False,
                study_id=study_id,
                rel_map=rel_map,
                target_rows_cache=target_rows_cache,
                target_pack_cache=target_pack_cache,
                pack_version=local_metrics.pack_version,
                metrics=local_metrics,
            )
        except Exception as exc:
            logger.exception(
                "dqa_submission_evaluation_failed",
                project_id=project_id,
                submission_id=submission.id,
            )
            local_metrics.evaluation_errors.append(f"{submission.id}: {exc}")
            continue
        if flags:
            flagged_submissions += 1
    db.commit()
    local_metrics.submissions = len(targets)
    local_metrics.flagged_submissions = flagged_submissions
    local_metrics.duration_ms = (time.perf_counter() - started) * 1000.0
    logger.info(
        "dqa_evaluate",
        project_id=project_id,
        submissions=local_metrics.submissions,
        flags=local_metrics.flags_produced,
        duration_ms=round(local_metrics.duration_ms, 1),
        errors=len(local_metrics.evaluation_errors),
    )
    result = {
        "submissions": local_metrics.submissions,
        "flagged_submissions": local_metrics.flagged_submissions,
        "flags": local_metrics.flags_produced,
        "metrics": local_metrics.to_dict(),
    }
    return result


def evaluate_project_cascade(db: Session, project_id: str) -> dict[str, Any]:
    """Recompute project and source projects that depend on it as a relationship target."""
    aggregate = EvaluationMetrics()
    stats = evaluate_project(db, project_id, metrics=aggregate)
    cascade_projects = [project_id]
    for source_id in source_projects_for_target(db, project_id):
        if source_id in cascade_projects:
            continue
        source_stats = evaluate_project(db, source_id, metrics=aggregate)
        cascade_projects.append(source_id)
        for key in ("submissions", "flagged_submissions", "flags"):
            stats[key] = stats.get(key, 0) + source_stats.get(key, 0)
    aggregate.cascade_projects = cascade_projects
    stats["cascade_projects"] = cascade_projects
    stats["metrics"] = aggregate.to_dict()
    return stats
