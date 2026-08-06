from __future__ import annotations

from datetime import datetime
from statistics import median
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, Submission
from app.db.session import get_db
from app.schemas.common import DqaFlagsQuery, ProjectIdQuery, StudyIdQuery, StudyProjectQuery
from app.schemas.dqa import (
    DqaFlagOut,
    DqaRecomputeResult,
    DqaRuleCount,
    DqaSummary,
    EnumeratorStat,
    FormFieldOut,
    ProjectDqaStat,
    RulePackOut,
    RulePackUpdate,
    TriangulationViewInfo,
    TriangulationViewOut,
)
from app.services import dqa_engine
from app.services.dqa_engine import list_form_fields

router = APIRouter(prefix="/dqa", tags=["dqa"])


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _flag_out(
    flag: DqaFlag,
    submission: Submission | None = None,
    *,
    pack: dict | None = None,
    rule: dict | None = None,
    project_rows: list[Submission] | None = None,
) -> DqaFlagOut:
    details = flag.details if isinstance(flag.details, dict) else {}
    data = submission.data if submission and isinstance(submission.data, dict) else {}
    highlight = dqa_engine.highlight_fields_for_flag(
        pack=pack,
        rule=rule,
        details=details,
        data=data,
    )
    enriched = dict(details)
    if highlight:
        enriched["highlightFields"] = highlight
    related = dqa_engine.enrich_flag_related_submissions(
        pack=pack,
        rule=rule,
        details=enriched,
        project_rows=project_rows or [],
    )
    if related:
        enriched["relatedSubmissions"] = related
        enriched["count"] = enriched.get("count") or len(related)
    return DqaFlagOut(
        id=flag.id,
        submission_id=flag.submission_id,
        project_id=flag.project_id,
        rule_id=flag.rule_id,
        severity=flag.severity,
        title=flag.title,
        message=flag.message,
        details=enriched or None,
        evaluated_at=_iso(flag.evaluated_at),
        enumerator=submission.enumerator if submission else None,
        project_name=submission.project_name if submission else None,
        kobo_id=submission.kobo_id if submission else None,
        submitted_at=_iso(submission.submitted_at) if submission and submission.submitted_at else None,
    )


@router.get("/summary", response_model=DqaSummary, operation_id="getDqaSummary")
def dqa_summary(
    q: Annotated[StudyProjectQuery, Query()],
    db: Session = Depends(get_db),
) -> DqaSummary:
    project_id = q.project_id
    study_id = q.study_id
    sub_q = select(Submission)
    flag_q = select(DqaFlag)
    if study_id and not project_id:
        project_ids = [
            p.id
            for p in db.scalars(select(Project).where(Project.study_id == study_id)).all()
        ]
        if not project_ids:
            return DqaSummary(
                project_id=None,
                total_submissions=0,
                flagged_submissions=0,
                flagged_pct=0.0,
                red_flags=0,
                amber_flags=0,
                by_rule=[],
            )
        sub_q = sub_q.where(Submission.project_id.in_(project_ids))
        flag_q = flag_q.where(DqaFlag.project_id.in_(project_ids))
    elif project_id:
        sub_q = sub_q.where(Submission.project_id == project_id)
        flag_q = flag_q.where(DqaFlag.project_id == project_id)

    submissions = list(db.scalars(sub_q).all())
    flags = list(db.scalars(flag_q).all())
    flagged_ids = {f.submission_id for f in flags}
    red = sum(1 for f in flags if f.severity == "red")
    amber = sum(1 for f in flags if f.severity == "amber")
    by_rule: dict[str, DqaRuleCount] = {}
    for flag in flags:
        key = flag.rule_id
        if key not in by_rule:
            by_rule[key] = DqaRuleCount(
                rule_id=flag.rule_id,
                title=flag.title,
                severity=flag.severity,
                count=0,
            )
        by_rule[key].count += 1
    total = len(submissions)
    flagged = len(flagged_ids)
    return DqaSummary(
        project_id=project_id,
        total_submissions=total,
        flagged_submissions=flagged,
        flagged_pct=round((flagged / total) * 100, 1) if total else 0.0,
        red_flags=red,
        amber_flags=amber,
        by_rule=sorted(by_rule.values(), key=lambda r: (-r.count, r.rule_id)),
    )


@router.get("/by-project", response_model=list[ProjectDqaStat], operation_id="getDqaByProject")
def dqa_by_project(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> list[ProjectDqaStat]:
    """Per-project DQA metrics aligned with the Data Quality dashboard."""
    study_id = q.study_id
    project_q = select(Project).order_by(Project.name)
    if study_id:
        project_q = project_q.where(Project.study_id == study_id)
    projects = list(db.scalars(project_q).all())
    project_ids = [p.id for p in projects]
    submissions = list(
        db.scalars(
            select(Submission).where(Submission.project_id.in_(project_ids))
            if project_ids
            else select(Submission).where(False)
        ).all()
    )
    flags = list(
        db.scalars(
            select(DqaFlag).where(DqaFlag.project_id.in_(project_ids))
            if project_ids
            else select(DqaFlag).where(False)
        ).all()
    )

    subs_by_project: dict[str, list[Submission]] = {}
    for sub in submissions:
        subs_by_project.setdefault(sub.project_id, []).append(sub)

    flags_by_sub: dict[str, list[DqaFlag]] = {}
    for flag in flags:
        flags_by_sub.setdefault(flag.submission_id, []).append(flag)

    results: list[ProjectDqaStat] = []
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
            ProjectDqaStat(
                project_id=project.id,
                project_name=project.name,
                total_submissions=total,
                clean_submissions=clean,
                amber_submissions=amber_subs,
                red_submissions=red_subs,
                red_flags=red_flags,
                amber_flags=amber_flags,
                flagged_pct=round((flagged / total) * 100, 1) if total else 0.0,
            )
        )
    return sorted(results, key=lambda r: (-r.flagged_pct, -r.total_submissions, r.project_name))


@router.get("/flags", response_model=list[DqaFlagOut], operation_id="getDqaFlags")
def list_flags(
    params: Annotated[DqaFlagsQuery, Query()],
    db: Session = Depends(get_db),
) -> list[DqaFlagOut]:
    project_id = params.project_id
    study_id = params.study_id
    submission_id = params.submission_id
    rule_id = params.rule_id
    severity = params.severity
    enumerator = params.enumerator
    limit = params.limit
    q = select(DqaFlag).order_by(DqaFlag.evaluated_at.desc()).limit(limit)
    if study_id and not project_id:
        project_ids = [
            p.id
            for p in db.scalars(select(Project).where(Project.study_id == study_id)).all()
        ]
        if not project_ids:
            return []
        q = q.where(DqaFlag.project_id.in_(project_ids))
    elif project_id:
        q = q.where(DqaFlag.project_id == project_id)
    if submission_id:
        q = q.where(DqaFlag.submission_id == submission_id)
    if rule_id:
        q = q.where(DqaFlag.rule_id == rule_id)
    if severity:
        q = q.where(DqaFlag.severity == severity.lower())
    flags = list(db.scalars(q).all())
    sub_ids = {f.submission_id for f in flags}
    submissions = {
        s.id: s
        for s in db.scalars(select(Submission).where(Submission.id.in_(sub_ids))).all()
    } if sub_ids else {}
    pack_cache: dict[str, dict | None] = {}
    rule_cache: dict[tuple[str, str], dict | None] = {}
    project_rows_cache: dict[str, list[Submission]] = {}
    results: list[DqaFlagOut] = []
    for flag in flags:
        sub = submissions.get(flag.submission_id)
        if enumerator and (not sub or enumerator.lower() not in (sub.enumerator or "").lower()):
            continue
        if flag.project_id not in pack_cache:
            pack_cache[flag.project_id] = dqa_engine.get_pack_for_project(db, flag.project_id)
        pack = pack_cache[flag.project_id]
        rule_key = (flag.project_id, flag.rule_id)
        if rule_key not in rule_cache:
            rule = None
            if isinstance(pack, dict):
                for item in pack.get("rules") or []:
                    if isinstance(item, dict) and str(item.get("id")) == flag.rule_id:
                        rule = item
                        break
            rule_cache[rule_key] = rule
        needs_related = False
        details = flag.details if isinstance(flag.details, dict) else {}
        op = str(details.get("op") or "")
        rule = rule_cache[rule_key]
        if op in {"unique_in_project", "group_count_lte"} or (
            isinstance(rule, dict)
            and isinstance(rule.get("check"), dict)
            and rule["check"].get("op") in {"unique_in_project", "group_count_lte"}
        ):
            needs_related = True
        if needs_related and flag.project_id not in project_rows_cache:
            project_rows_cache[flag.project_id] = list(
                db.scalars(select(Submission).where(Submission.project_id == flag.project_id)).all()
            )
        results.append(
            _flag_out(
                flag,
                sub,
                pack=pack,
                rule=rule,
                project_rows=project_rows_cache.get(flag.project_id),
            )
        )
    return results


@router.get("/enumerators", response_model=list[EnumeratorStat], operation_id="getDqaEnumerators")
def enumerator_stats(
    q: Annotated[StudyProjectQuery, Query()],
    db: Session = Depends(get_db),
) -> list[EnumeratorStat]:
    project_id = q.project_id
    study_id = q.study_id
    sub_q = select(Submission)
    flag_q = select(DqaFlag)
    if study_id and not project_id:
        project_ids = [
            p.id
            for p in db.scalars(select(Project).where(Project.study_id == study_id)).all()
        ]
        if not project_ids:
            return []
        sub_q = sub_q.where(Submission.project_id.in_(project_ids))
        flag_q = flag_q.where(DqaFlag.project_id.in_(project_ids))
    elif project_id:
        sub_q = sub_q.where(Submission.project_id == project_id)
        flag_q = flag_q.where(DqaFlag.project_id == project_id)
    submissions = list(db.scalars(sub_q).all())
    flags = list(db.scalars(flag_q).all())
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

    result: list[EnumeratorStat] = []
    for name, bucket in buckets.items():
        total = bucket["submissions"]
        flagged = bucket["flagged"]
        durations = bucket["durations"]
        result.append(
            EnumeratorStat(
                enumerator=name,
                submissions=total,
                flagged=flagged,
                flagged_pct=round((flagged / total) * 100, 1) if total else 0.0,
                red_flags=bucket["red"],
                amber_flags=bucket["amber"],
                median_duration_minutes=round(median(durations), 1) if durations else None,
            )
        )
    return sorted(result, key=lambda r: (-r.flagged_pct, -r.submissions, r.enumerator))


@router.post("/recompute", response_model=DqaRecomputeResult, operation_id="recomputeDqa")
def recompute(
    q: Annotated[ProjectIdQuery, Query()],
    db: Session = Depends(get_db),
) -> DqaRecomputeResult:
    project_id = q.project_id
    if project_id:
        if not db.get(Project, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        stats = dqa_engine.evaluate_project(db, project_id)
        return DqaRecomputeResult(project_id=project_id, **stats)

    totals = {"submissions": 0, "flagged_submissions": 0, "flags": 0}
    for project in db.scalars(select(Project)).all():
        stats = dqa_engine.evaluate_project(db, project.id)
        for key in totals:
            totals[key] += stats[key]
    return DqaRecomputeResult(project_id=None, **totals)


@router.get(
    "/triangulation",
    response_model=list[TriangulationViewInfo],
    operation_id="getTriangulationViews",
)
def list_triangulation_views() -> list[TriangulationViewInfo]:
    from app.services import triangulation as tri

    return [TriangulationViewInfo.model_validate(v) for v in tri.list_triangulation_views()]


@router.get(
    "/triangulation/{view_id}",
    response_model=TriangulationViewOut,
    operation_id="getTriangulationView",
)
def triangulation_view(
    view_id: str,
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> TriangulationViewOut:
    """UDISE-joined triangulation views: TR-1, TR-3, TR-5 (study-scoped when studyId set)."""
    from app.services import triangulation as tri

    try:
        return tri.build_view(db, view_id, study_id=q.study_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown triangulation view. Supported: {', '.join(tri.SUPPORTED_VIEWS)}.",
        ) from exc


# Project-scoped pack / field endpoints mounted under /projects as well via include
projects_router = APIRouter(prefix="/projects", tags=["dqa"])


@projects_router.get(
    "/{project_id}/form-fields",
    response_model=list[FormFieldOut],
    operation_id="getProjectFormFields",
)
def project_form_fields(project_id: str, db: Session = Depends(get_db)) -> list[FormFieldOut]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    fields = list_form_fields(
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    return [FormFieldOut.model_validate(f) for f in fields]


@projects_router.get(
    "/{project_id}/rule-pack",
    response_model=RulePackOut,
    operation_id="getProjectRulePack",
)
def get_rule_pack(project_id: str, db: Session = Depends(get_db)) -> RulePackOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    pack = dqa_engine.get_pack_for_project(db, project_id) or {
        "id": project.uid,
        "project_uids": [project.uid],
        "fields": {},
        "thresholds": {},
        "rules": [],
    }
    return RulePackOut(project_id=project_id, pack=pack)


@projects_router.put(
    "/{project_id}/rule-pack",
    response_model=RulePackOut,
    operation_id="updateProjectRulePack",
)
def put_rule_pack(
    project_id: str,
    payload: RulePackUpdate,
    db: Session = Depends(get_db),
) -> RulePackOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not isinstance(payload.pack, dict):
        raise HTTPException(status_code=400, detail="pack must be an object")
    saved = dqa_engine.save_pack(db, project_id, payload.pack)
    return RulePackOut(project_id=project_id, pack=saved)
