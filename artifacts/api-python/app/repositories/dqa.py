"""DQA query repository — submissions/flags aggregation for dashboard endpoints."""

from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import DqaFlag, Project, Study, Submission
from app.domain.time_window import resolve_optional_submitted_at_bounds


def project_ids_for_study(db: Session, study_id: str) -> list[str]:
    return [
        p.id
        for p in db.scalars(select(Project).where(Project.study_id == study_id)).all()
    ]


def study_timezone(db: Session, study_id: str | None) -> str:
    if not study_id:
        return "UTC"
    study = db.get(Study, study_id)
    if study is None:
        return "UTC"
    return (study.timezone or "UTC").strip() or "UTC"


def _apply_submitted_at_window(
    query: Select[Any],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    timezone: str = "UTC",
) -> Select[Any]:
    start, finish = resolve_optional_submitted_at_bounds(
        date_from, date_to, timezone=timezone
    )
    if start is not None:
        query = query.where(Submission.submitted_at >= start)
    if finish is not None:
        query = query.where(Submission.submitted_at < finish)
    return query


def load_submissions_and_flags(
    db: Session,
    *,
    project_id: str | None = None,
    study_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[Submission], list[DqaFlag]] | None:
    """Return (submissions, flags) scoped by study or project.

    Optional ``date_from`` / ``date_to`` filter by submission ``submitted_at``.
    Returns ``None`` when study scope has no projects (caller should return empty).
    """
    sub_q = select(Submission)
    flag_q = select(DqaFlag)
    if study_id and not project_id:
        project_ids = project_ids_for_study(db, study_id)
        if not project_ids:
            return None
        sub_q = sub_q.where(Submission.project_id.in_(project_ids))
        flag_q = flag_q.where(DqaFlag.project_id.in_(project_ids))
    elif project_id:
        sub_q = sub_q.where(Submission.project_id == project_id)
        flag_q = flag_q.where(DqaFlag.project_id == project_id)

    if date_from or date_to:
        tz = study_timezone(db, study_id)
        if not study_id and project_id:
            project = db.get(Project, project_id)
            tz = study_timezone(db, project.study_id if project else None)
        sub_q = _apply_submitted_at_window(
            sub_q, date_from=date_from, date_to=date_to, timezone=tz
        )
        flag_q = flag_q.join(Submission, Submission.id == DqaFlag.submission_id)
        flag_q = _apply_submitted_at_window(
            flag_q, date_from=date_from, date_to=date_to, timezone=tz
        )

    return list(db.scalars(sub_q).all()), list(db.scalars(flag_q).all())


def load_projects_with_dqa(
    db: Session,
    *,
    study_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[list[Project], list[Submission], list[DqaFlag]]:
    project_q = select(Project).order_by(Project.name)
    if study_id:
        project_q = project_q.where(Project.study_id == study_id)
    projects = list(db.scalars(project_q).all())
    project_ids = [p.id for p in projects]
    if not project_ids:
        return projects, [], []

    sub_q = select(Submission).where(Submission.project_id.in_(project_ids))
    flag_q = select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))
    if date_from or date_to:
        tz = study_timezone(db, study_id)
        sub_q = _apply_submitted_at_window(
            sub_q, date_from=date_from, date_to=date_to, timezone=tz
        )
        flag_q = flag_q.join(Submission, Submission.id == DqaFlag.submission_id)
        flag_q = _apply_submitted_at_window(
            flag_q, date_from=date_from, date_to=date_to, timezone=tz
        )

    return projects, list(db.scalars(sub_q).all()), list(db.scalars(flag_q).all())


def load_flags_filtered(
    db: Session,
    *,
    project_id: str | None = None,
    study_id: str | None = None,
    submission_id: str | None = None,
    rule_id: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 100,
) -> list[DqaFlag] | None:
    """Return filtered flags, or ``None`` when study scope is empty."""
    q = select(DqaFlag).order_by(DqaFlag.evaluated_at.desc()).limit(limit)
    if study_id and not project_id:
        project_ids = project_ids_for_study(db, study_id)
        if not project_ids:
            return None
        q = q.where(DqaFlag.project_id.in_(project_ids))
    elif project_id:
        q = q.where(DqaFlag.project_id == project_id)
    if submission_id:
        q = q.where(DqaFlag.submission_id == submission_id)
    if rule_id:
        q = q.where(DqaFlag.rule_id == rule_id)
    if severity:
        q = q.where(DqaFlag.severity == severity.lower())
    if date_from or date_to:
        tz = study_timezone(db, study_id)
        if not study_id and project_id:
            project = db.get(Project, project_id)
            tz = study_timezone(db, project.study_id if project else None)
        q = q.join(Submission, Submission.id == DqaFlag.submission_id)
        q = _apply_submitted_at_window(
            q, date_from=date_from, date_to=date_to, timezone=tz
        )
    return list(db.scalars(q).all())


def load_submissions_by_ids(db: Session, sub_ids: set[str]) -> dict[str, Submission]:
    if not sub_ids:
        return {}
    return {
        s.id: s
        for s in db.scalars(
            select(Submission)
            .options(joinedload(Submission.project))
            .where(Submission.id.in_(sub_ids))
        )
        .unique()
        .all()
    }


def load_project_submissions(db: Session, project_id: str) -> list[Submission]:
    return list(
        db.scalars(select(Submission).where(Submission.project_id == project_id)).all()
    )


def aggregate_summary(
    submissions: list[Submission], flags: list[DqaFlag]
) -> dict[str, Any]:
    flagged_ids = {f.submission_id for f in flags}
    red = sum(1 for f in flags if f.severity == "red")
    amber = sum(1 for f in flags if f.severity == "amber")
    by_rule: dict[str, dict[str, Any]] = {}
    for flag in flags:
        key = flag.rule_id
        if key not in by_rule:
            by_rule[key] = {
                "rule_id": flag.rule_id,
                "title": flag.title,
                "severity": flag.severity,
                "count": 0,
            }
        by_rule[key]["count"] += 1
    total = len(submissions)
    flagged = len(flagged_ids)
    return {
        "total_submissions": total,
        "flagged_submissions": flagged,
        "flagged_pct": round((flagged / total) * 100, 1) if total else 0.0,
        "red_flags": red,
        "amber_flags": amber,
        "by_rule": sorted(by_rule.values(), key=lambda r: (-r["count"], r["rule_id"])),
    }


def aggregate_by_project(
    projects: list[Project],
    submissions: list[Submission],
    flags: list[DqaFlag],
) -> list[dict[str, Any]]:
    subs_by_project: dict[str, list[Submission]] = {}
    for sub in submissions:
        subs_by_project.setdefault(sub.project_id, []).append(sub)

    flags_by_sub: dict[str, list[DqaFlag]] = {}
    for flag in flags:
        flags_by_sub.setdefault(flag.submission_id, []).append(flag)

    results: list[dict[str, Any]] = []
    for project in projects:
        project_subs = subs_by_project.get(project.id, [])
        total = len(project_subs)
        clean = 0
        amber_subs = 0
        red_subs = 0
        red_flags = 0
        amber_flags = 0
        for sub in project_subs:
            sub_flags = flags_by_sub.get(sub.id, [])
            red_n = sum(1 for f in sub_flags if f.severity == "red")
            amber_n = sum(1 for f in sub_flags if f.severity == "amber")
            red_flags += red_n
            amber_flags += amber_n
            if red_n > 0:
                red_subs += 1
            elif amber_n > 0:
                amber_subs += 1
            else:
                clean += 1
        flagged = amber_subs + red_subs
        results.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "total_submissions": total,
                "clean_submissions": clean,
                "amber_submissions": amber_subs,
                "red_submissions": red_subs,
                "red_flags": red_flags,
                "amber_flags": amber_flags,
                "flagged_pct": round((flagged / total) * 100, 1) if total else 0.0,
            }
        )
    return sorted(
        results, key=lambda r: (-r["flagged_pct"], -r["total_submissions"], r["project_name"])
    )


def aggregate_enumerators(
    submissions: list[Submission], flags: list[DqaFlag]
) -> list[dict[str, Any]]:
    flags_by_sub: dict[str, list[DqaFlag]] = {}
    for flag in flags:
        flags_by_sub.setdefault(flag.submission_id, []).append(flag)

    buckets: dict[str, dict] = {}
    for sub in submissions:
        name = sub.enumerator or "Unknown"
        bucket = buckets.setdefault(
            name,
            {"submissions": 0, "flagged": 0, "red": 0, "amber": 0, "durations": []},
        )
        bucket["submissions"] += 1
        sub_flags = flags_by_sub.get(sub.id, [])
        if sub_flags:
            bucket["flagged"] += 1
        bucket["red"] += sum(1 for f in sub_flags if f.severity == "red")
        bucket["amber"] += sum(1 for f in sub_flags if f.severity == "amber")
        data = sub.data if isinstance(sub.data, dict) else {}
        start = data.get("start")
        end = data.get("end")
        try:
            if start and end:
                from datetime import datetime

                s = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                e = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
                bucket["durations"].append((e - s).total_seconds() / 60.0)
        except ValueError:
            pass

    result: list[dict[str, Any]] = []
    for name, bucket in buckets.items():
        total = bucket["submissions"]
        flagged = bucket["flagged"]
        durations = bucket["durations"]
        result.append(
            {
                "enumerator": name,
                "submissions": total,
                "flagged": flagged,
                "flagged_pct": round((flagged / total) * 100, 1) if total else 0.0,
                "red_flags": bucket["red"],
                "amber_flags": bucket["amber"],
                "median_duration_minutes": round(median(durations), 1) if durations else None,
            }
        )
    return sorted(result, key=lambda r: (-r["flagged_pct"], -r["submissions"], r["enumerator"]))
