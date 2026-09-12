from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Study
from app.db.session import get_db
from app.repositories import dqa as dqa_repo
from app.schemas.common import DqaDashboardQuery, DqaFlagsQuery, StudyDateRangeQuery, StudyIdQuery, StudyProjectQuery
from app.schemas.dqa import (
    DqaCompileSessionOut,
    DqaCompileInput,
    DqaCompileInvalid,
    DqaCompileNeedsClarification,
    DqaCompileSuccess,
    DqaFlagOut,
    DqaRelationshipCreate,
    DqaRelationshipOut,
    DqaRelationshipUpdate,
    DqaRecomputeResult,
    DqaRuleCount,
    DqaSummary,
    DqaExplainFlagInput,
    DqaExplainFlagOut,
    DqaRuleLifecycleInput,
    DqaTestRuleInput,
    DqaTestRuleOut,
    DqaValidateRuleInput,
    DqaValidateRuleOut,
    EnumeratorStat,
    FormFieldOut,
    ProjectDqaStat,
    RulePackOut,
    RulePackUpdate,
    RulePackVersionOut,
    TriangulationViewInfo,
    TriangulationViewOut,
)
from app.services import dqa_engine
from app.services.dqa_compile_audit import get_compile_session, list_compile_sessions
from app.services.dqa_compile import (
    CompileError,
    camelize,
    compile_dqa_rule,
    compile_dqa_rule_stream,
    validate_dqa_rule_for_project,
)
from app.services.dqa_relationships import (
    RelationshipError,
    create_relationship,
    delete_relationship,
    list_relationships,
    update_relationship,
    validate_relationship_payload,
)
from app.services.dqa_rule_packs import get_pack_version, list_pack_versions
from app.domain.dqa.form_fields import list_form_fields
from app.domain.dqa.rule_management import filter_rules, set_rule_status
from app.services.dqa_test import explain_flag, run_rule_test
from app.domain.dqa.validate import validate_pack_rules
from app.services.settings import get_or_create_settings
from app.services import triangulation as tri
from app.services.triangulation import TriangulationError

router = APIRouter(prefix="/dqa", tags=["dqa"])


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _flag_out(
    flag,
    submission=None,
    *,
    pack: dict | None = None,
    rule: dict | None = None,
    project_rows: list | None = None,
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
        project_name=(
            submission.project.name
            if submission and submission.project is not None
            else None
        ),
        kobo_id=submission.kobo_id if submission else None,
        submitted_at=_iso(submission.submitted_at) if submission and submission.submitted_at else None,
    )


def _require_project_or_study(project_id: str | None, study_id: str | None) -> None:
    if not project_id and not study_id:
        raise HTTPException(
            status_code=400, detail="studyId or projectId is required"
        )


@router.get("/summary", response_model=DqaSummary, operation_id="getDqaSummary")
def dqa_summary(
    q: Annotated[DqaDashboardQuery, Query()],
    db: Session = Depends(get_db),
) -> DqaSummary:
    _require_project_or_study(q.project_id, q.study_id)
    loaded = dqa_repo.load_submissions_and_flags(
        db,
        project_id=q.project_id,
        study_id=q.study_id,
        date_from=q.date_from,
        date_to=q.date_to,
    )
    if loaded is None:
        return DqaSummary(
            project_id=None,
            total_submissions=0,
            flagged_submissions=0,
            flagged_pct=0.0,
            red_flags=0,
            amber_flags=0,
            by_rule=[],
        )
    submissions, flags = loaded
    agg = dqa_repo.aggregate_summary(submissions, flags)
    return DqaSummary(
        project_id=q.project_id,
        total_submissions=agg["total_submissions"],
        flagged_submissions=agg["flagged_submissions"],
        flagged_pct=agg["flagged_pct"],
        red_flags=agg["red_flags"],
        amber_flags=agg["amber_flags"],
        by_rule=[DqaRuleCount(**r) for r in agg["by_rule"]],
    )


@router.get("/by-project", response_model=list[ProjectDqaStat], operation_id="getDqaByProject")
def dqa_by_project(
    q: Annotated[StudyDateRangeQuery, Query()],
    db: Session = Depends(get_db),
) -> list[ProjectDqaStat]:
    """Per-project DQA metrics aligned with the Data Quality dashboard."""
    projects, submissions, flags = dqa_repo.load_projects_with_dqa(
        db,
        study_id=q.study_id,
        date_from=q.date_from,
        date_to=q.date_to,
    )
    rows = dqa_repo.aggregate_by_project(projects, submissions, flags)
    return [ProjectDqaStat(**r) for r in rows]


@router.get("/flags", response_model=list[DqaFlagOut], operation_id="getDqaFlags")
def list_flags(
    params: Annotated[DqaFlagsQuery, Query()],
    db: Session = Depends(get_db),
) -> list[DqaFlagOut]:
    if not params.submission_id:
        _require_project_or_study(params.project_id, params.study_id)
    flags = dqa_repo.load_flags_filtered(
        db,
        project_id=params.project_id,
        study_id=params.study_id,
        submission_id=params.submission_id,
        rule_id=params.rule_id,
        severity=params.severity,
        date_from=params.date_from,
        date_to=params.date_to,
        limit=params.limit,
    )
    if flags is None:
        return []
    submissions = dqa_repo.load_submissions_by_ids(db, {f.submission_id for f in flags})
    pack_cache: dict[str, dict | None] = {}
    rule_cache: dict[tuple[str, str], dict | None] = {}
    project_rows_cache: dict[str, list] = {}
    results: list[DqaFlagOut] = []
    for flag in flags:
        sub = submissions.get(flag.submission_id)
        if params.enumerator and (
            not sub or params.enumerator.lower() not in (sub.enumerator or "").lower()
        ):
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
            project_rows_cache[flag.project_id] = dqa_repo.load_project_submissions(
                db, flag.project_id
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
    q: Annotated[DqaDashboardQuery, Query()],
    db: Session = Depends(get_db),
) -> list[EnumeratorStat]:
    _require_project_or_study(q.project_id, q.study_id)
    loaded = dqa_repo.load_submissions_and_flags(
        db,
        project_id=q.project_id,
        study_id=q.study_id,
        date_from=q.date_from,
        date_to=q.date_to,
    )
    if loaded is None:
        return []
    submissions, flags = loaded
    rows = dqa_repo.aggregate_enumerators(submissions, flags)
    return [EnumeratorStat(**r) for r in rows]


@router.post("/recompute", response_model=DqaRecomputeResult, operation_id="recomputeDqa")
def recompute(
    q: Annotated[StudyProjectQuery, Query()],
    db: Session = Depends(get_db),
) -> DqaRecomputeResult:
    project_id = q.project_id
    if project_id:
        if not db.get(Project, project_id):
            raise HTTPException(status_code=404, detail="Project not found")
        stats = dqa_engine.evaluate_project_cascade(db, project_id)
        return DqaRecomputeResult(project_id=project_id, **stats)

    if not q.study_id:
        raise HTTPException(
            status_code=400, detail="studyId or projectId is required"
        )
    if not db.get(Study, q.study_id):
        raise HTTPException(status_code=404, detail="Study not found")
    projects = db.scalars(
        select(Project).where(Project.study_id == q.study_id)
    ).all()

    totals = {"submissions": 0, "flagged_submissions": 0, "flags": 0}
    for project in projects:
        stats = dqa_engine.evaluate_project(db, project.id)
        for key in totals:
            totals[key] += stats[key]
    return DqaRecomputeResult(project_id=None, **totals)


@router.get(
    "/relationships",
    response_model=list[DqaRelationshipOut],
    operation_id="listDqaRelationships",
)
def list_dqa_relationships(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> list[DqaRelationshipOut]:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    rows = list_relationships(db, q.study_id)
    return [DqaRelationshipOut.model_validate(row, from_attributes=True) for row in rows]


@router.post(
    "/relationships",
    response_model=DqaRelationshipOut,
    operation_id="createDqaRelationship",
)
def create_dqa_relationship(
    q: Annotated[StudyIdQuery, Query()],
    payload: DqaRelationshipCreate,
    db: Session = Depends(get_db),
) -> DqaRelationshipOut:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    validation = validate_relationship_payload(db, q.study_id, payload.model_dump())
    if not validation.valid:
        raise HTTPException(status_code=400, detail=validation.to_dict())
    try:
        row = create_relationship(db, q.study_id, payload.model_dump())
    except RelationshipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return DqaRelationshipOut.model_validate(row, from_attributes=True)


@router.put(
    "/relationships/{relationship_id}",
    response_model=DqaRelationshipOut,
    operation_id="updateDqaRelationship",
)
def update_dqa_relationship(
    relationship_id: str,
    q: Annotated[StudyIdQuery, Query()],
    payload: DqaRelationshipUpdate,
    db: Session = Depends(get_db),
) -> DqaRelationshipOut:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    try:
        row = update_relationship(
            db,
            q.study_id,
            relationship_id,
            payload.model_dump(exclude_unset=True),
        )
    except RelationshipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return DqaRelationshipOut.model_validate(row, from_attributes=True)


@router.delete(
    "/relationships/{relationship_id}",
    operation_id="deleteDqaRelationship",
)
def delete_dqa_relationship(
    relationship_id: str,
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId is required")
    try:
        delete_relationship(db, q.study_id, relationship_id)
    except RelationshipError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.get(
    "/triangulation",
    response_model=list[TriangulationViewInfo],
    operation_id="getTriangulationViews",
)
def list_triangulation_views(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> list[TriangulationViewInfo]:
    """List triangulation views defined for a study. studyId is required."""
    try:
        return [TriangulationViewInfo.model_validate(v) for v in tri.list_views(db, q.study_id)]
    except TriangulationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    """Evaluate a study-defined triangulation view. studyId is required."""
    try:
        return tri.build_view(db, view_id, study_id=q.study_id)
    except TriangulationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


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
    return RulePackOut(
        project_id=project_id,
        pack=pack,
        version=get_pack_version(db, project_id) or pack.get("pack_version") or 1,
    )


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
    form_fields = list_form_fields(
        project.form_definition if isinstance(project.form_definition, dict) else None
    )
    validation = validate_pack_rules(
        payload.pack.get("rules") if isinstance(payload.pack.get("rules"), list) else [],
        form_fields=form_fields,
        pack=payload.pack,
    )
    if not validation.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Rule pack contains invalid rules",
                "validation": validation.to_dict(),
            },
        )
    try:
        saved = dqa_engine.save_pack(db, project_id, payload.pack, source="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RulePackOut(
        project_id=project_id,
        pack=saved,
        version=int(saved.get("pack_version") or get_pack_version(db, project_id) or 1),
    )


@projects_router.get(
    "/{project_id}/rule-pack/versions",
    response_model=list[RulePackVersionOut],
    operation_id="listProjectRulePackVersions",
)
def list_rule_pack_versions(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[RulePackVersionOut]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = list_pack_versions(db, project_id, limit=limit)
    return [
        RulePackVersionOut(
            id=row.id,
            project_id=row.project_id,
            version=row.version,
            status=row.status,
            source=row.source,
            compile_session_id=row.compile_session_id,
            change_note=row.change_note,
            created_at=_iso(row.created_at),
            rule_count=len((row.pack or {}).get("rules") or []),
        )
        for row in rows
    ]


@projects_router.get(
    "/{project_id}/dqa/compile-sessions/{session_id}",
    response_model=DqaCompileSessionOut,
    operation_id="getDqaCompileSession",
)
def get_dqa_compile_session(
    project_id: str,
    session_id: str,
    db: Session = Depends(get_db),
) -> DqaCompileSessionOut:
    row = get_compile_session(db, session_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="Compile session not found")
    return DqaCompileSessionOut(
        id=row.id,
        project_id=row.project_id,
        study_id=row.study_id,
        status=row.status,
        english=row.english,
        provider=row.provider,
        model=row.model,
        attempts=row.attempts,
        latency_ms_total=row.latency_ms_total,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        rule_id=row.rule_id,
        created_at=_iso(row.created_at),
    )


@projects_router.get(
    "/{project_id}/dqa/compile-sessions",
    response_model=list[DqaCompileSessionOut],
    operation_id="listDqaCompileSessions",
)
def list_dqa_compile_sessions(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[DqaCompileSessionOut]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    rows = list_compile_sessions(db, project_id, limit=limit)
    return [
        DqaCompileSessionOut(
            id=row.id,
            project_id=row.project_id,
            study_id=row.study_id,
            status=row.status,
            english=row.english,
            provider=row.provider,
            model=row.model,
            attempts=row.attempts,
            latency_ms_total=row.latency_ms_total,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            rule_id=row.rule_id,
            created_at=_iso(row.created_at),
        )
        for row in rows
    ]


@projects_router.post(
    "/{project_id}/dqa/test-rule",
    response_model=DqaTestRuleOut,
    operation_id="testDqaRule",
)
def test_dqa_rule(
    project_id: str,
    payload: DqaTestRuleInput,
    db: Session = Depends(get_db),
) -> DqaTestRuleOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = run_rule_test(
        db,
        project_id,
        payload.rule,
        submission_ids=payload.submission_ids or None,
        limit=payload.limit,
    )
    return DqaTestRuleOut.model_validate(result)


@projects_router.post(
    "/{project_id}/dqa/explain",
    response_model=DqaExplainFlagOut,
    operation_id="explainDqaFlag",
)
def explain_dqa_flag(
    project_id: str,
    payload: DqaExplainFlagInput,
    db: Session = Depends(get_db),
) -> DqaExplainFlagOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = explain_flag(
        rule=payload.rule,
        details=payload.details,
        passes=payload.passes,
    )
    return DqaExplainFlagOut.model_validate(result)


@projects_router.post(
    "/{project_id}/dqa/rules/{rule_id}/lifecycle",
    operation_id="setDqaRuleLifecycle",
)
def set_dqa_rule_lifecycle(
    project_id: str,
    rule_id: str,
    payload: DqaRuleLifecycleInput,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    pack = dqa_engine.get_pack_for_project(db, project_id) or {"rules": []}
    rules = pack.get("rules") if isinstance(pack.get("rules"), list) else []
    updated_rule = None
    new_rules = []
    for item in rules:
        if not isinstance(item, dict):
            continue
        if str(item.get("id")) == rule_id:
            try:
                updated_rule = set_rule_status(item, payload.status, enabled=payload.enabled)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            new_rules.append(updated_rule)
        else:
            new_rules.append(item)
    if updated_rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    pack = dict(pack)
    pack["rules"] = new_rules
    saved = dqa_engine.save_pack(db, project_id, pack, source="manual", change_note=f"lifecycle:{payload.status}")
    return {"rule": updated_rule, "pack_version": saved.get("pack_version")}


@projects_router.get(
    "/{project_id}/dqa/rules",
    operation_id="listDqaRules",
)
def list_dqa_rules(
    project_id: str,
    q: str | None = Query(None),
    status: str | None = Query(None),
    group: str | None = Query(None),
    enabled_only: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    pack = dqa_engine.get_pack_for_project(db, project_id) or {}
    rules = filter_rules(
        pack.get("rules") if isinstance(pack.get("rules"), list) else [],
        query=q,
        status=status,
        group=group,
        enabled_only=enabled_only,
    )
    return rules


@projects_router.post(
    "/{project_id}/dqa/compile",
    operation_id="compileDqaRule",
    response_model=None,
)
def compile_rule(
    project_id: str,
    payload: DqaCompileInput,
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    settings = get_or_create_settings(db)
    try:
        result = compile_dqa_rule(
            db,
            project,
            english=payload.english,
            conversation=[t.model_dump() for t in payload.conversation],
            existing_rule=payload.existing_rule,
            preview_limit=payload.preview_limit,
            settings=settings,
        )
    except CompileError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    body = camelize(result)
    status = result.get("status")
    if status == "invalid":
        return JSONResponse(status_code=422, content=body)
    return body


@projects_router.post(
    "/{project_id}/dqa/compile/stream",
    operation_id="compileDqaRuleStream",
    response_model=None,
)
def compile_rule_stream(
    project_id: str,
    payload: DqaCompileInput,
    db: Session = Depends(get_db),
):
    """SSE stream of compile progress, optional tokens, then a final result/error event."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    settings = get_or_create_settings(db)

    def event_gen():
        import json

        try:
            for event in compile_dqa_rule_stream(
                db,
                project,
                english=payload.english,
                conversation=[t.model_dump() for t in payload.conversation],
                existing_rule=payload.existing_rule,
                preview_limit=payload.preview_limit,
                settings=settings,
            ):
                name = str(event.get("event") or "message")
                data = {k: v for k, v in event.items() if k != "event"}
                yield f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 — surface to client as SSE error
            yield f"event: error\ndata: {json.dumps({'message': str(exc), 'code': 'stream_error'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@projects_router.post(
    "/{project_id}/dqa/validate-rule",
    response_model=DqaValidateRuleOut,
    operation_id="validateDqaRule",
)
def validate_rule_endpoint(
    project_id: str,
    payload: DqaValidateRuleInput,
    db: Session = Depends(get_db),
) -> DqaValidateRuleOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = validate_dqa_rule_for_project(
        db,
        project,
        payload.rule,
        preview_limit=payload.preview_limit,
    )
    return DqaValidateRuleOut.model_validate(
        {
            "status": result["status"],
            "message": result.get("message"),
            "validation": result["validation"],
            "preview": result.get("preview"),
            "test": result.get("test"),
            "warnings": result.get("warnings") or [],
        }
    )
