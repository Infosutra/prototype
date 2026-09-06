from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, ReportSchedule
from app.db.session import get_db
from app.integrations.kobo import KoboApiError
from app.schemas.common import OkResponse
from app.schemas.dqa import (
    TriangulationViewDefinitionCreate,
    TriangulationViewDefinitionOut,
    TriangulationViewDefinitionUpdate,
)
from app.schemas.misc import ReportScheduleOut, ReportScheduleUpdate
from app.schemas.settings import ConnectionTestResult
from app.schemas.studies import (
    StudyAssignProject,
    StudyCreate,
    StudyCredentialSummary,
    StudyKoboUpdate,
    StudyOut,
    StudyUpdate,
)
from app.services import settings as settings_service
from app.services import studies as studies_service
from app.services import triangulation as tri_service

router = APIRouter(prefix="/studies", tags=["studies"])


def _out(study) -> StudyOut:
    return StudyOut.model_validate(studies_service.study_to_dict(study))


def _schedule_out(row: ReportSchedule) -> ReportScheduleOut:
    return ReportScheduleOut(
        id=row.id,
        study_id=row.study_id,
        report_type=row.report_type,
        enabled=bool(row.enabled),
        time=row.time or "21:30",
        timezone=row.timezone or "Asia/Kolkata",
        recipients=list(row.recipients or []),
        last_sent_on=row.last_sent_on,
    )


def _get_or_create_daily_schedule(db: Session, study_id: str) -> ReportSchedule:
    row = db.scalars(
        select(ReportSchedule).where(
            ReportSchedule.study_id == study_id,
            ReportSchedule.report_type == "daily_dqa",
        )
    ).first()
    if row:
        return row
    study = studies_service.get_study(db, study_id)
    row = ReportSchedule(
        id=str(uuid.uuid4()),
        study_id=study_id,
        report_type="daily_dqa",
        enabled=False,
        time="21:30",
        timezone=(study.timezone if study and study.timezone else "Asia/Kolkata"),
        recipients=[],
        last_sent_on=None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("", response_model=list[StudyOut], operation_id="getStudies")
def list_studies(db: Session = Depends(get_db)) -> list[StudyOut]:
    return [StudyOut.model_validate(item) for item in studies_service.list_studies(db)]


@router.post("", response_model=StudyOut, operation_id="createStudy")
def create_study(payload: StudyCreate, db: Session = Depends(get_db)) -> StudyOut:
    try:
        study = studies_service.create_study(db, payload.model_dump(by_alias=False))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(study)


@router.get("/{study_id}", response_model=StudyOut, operation_id="getStudy")
def get_study(study_id: str, db: Session = Depends(get_db)) -> StudyOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return _out(study)


@router.patch("/{study_id}", response_model=StudyOut, operation_id="updateStudy")
def update_study(
    study_id: str,
    payload: StudyUpdate,
    db: Session = Depends(get_db),
) -> StudyOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    data = payload.model_dump(exclude_unset=True, by_alias=False)
    try:
        study = studies_service.update_study(db, study, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _out(study)


@router.delete("/{study_id}", response_model=OkResponse, operation_id="deleteStudy")
def delete_study(study_id: str, db: Session = Depends(get_db)) -> OkResponse:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    studies_service.delete_study(db, study)
    return OkResponse(success=True)


@router.get(
    "/{study_id}/schedules/daily-dqa",
    response_model=ReportScheduleOut,
    operation_id="getStudySchedule",
)
def get_study_schedule(study_id: str, db: Session = Depends(get_db)) -> ReportScheduleOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return _schedule_out(_get_or_create_daily_schedule(db, study_id))


@router.put(
    "/{study_id}/schedules/daily-dqa",
    response_model=ReportScheduleOut,
    operation_id="updateStudySchedule",
)
def update_study_schedule(
    study_id: str,
    payload: ReportScheduleUpdate,
    db: Session = Depends(get_db),
) -> ReportScheduleOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    row = _get_or_create_daily_schedule(db, study_id)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.time is not None:
        row.time = payload.time.strip() or row.time
    if payload.timezone is not None:
        row.timezone = payload.timezone.strip() or row.timezone
    if payload.recipients is not None:
        row.recipients = [e.strip() for e in payload.recipients if e and e.strip()]
    db.commit()
    db.refresh(row)
    return _schedule_out(row)


@router.get(
    "/{study_id}/kobo",
    response_model=StudyCredentialSummary,
    operation_id="getStudyKobo",
)
def get_study_kobo(study_id: str, db: Session = Depends(get_db)) -> StudyCredentialSummary:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    cred = study.credential
    if not cred:
        return StudyCredentialSummary()
    return settings_service.credential_to_summary(cred)


@router.put(
    "/{study_id}/kobo",
    response_model=StudyCredentialSummary,
    operation_id="updateStudyKobo",
    responses={400: {"description": "Bad request"}},
)
def update_study_kobo(
    study_id: str,
    payload: StudyKoboUpdate,
    db: Session = Depends(get_db),
) -> StudyCredentialSummary:
    try:
        return settings_service.update_study_kobo(db, study_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, KoboApiError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


@router.post(
    "/{study_id}/test-kobo",
    response_model=ConnectionTestResult,
    operation_id="testStudyKoboConnection",
)
def test_study_kobo(study_id: str, db: Session = Depends(get_db)) -> ConnectionTestResult:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return settings_service.test_study_kobo(db, study_id)


@router.post("/{study_id}/projects", response_model=StudyOut, operation_id="assignStudyProject")
def assign_project(
    study_id: str,
    payload: StudyAssignProject,
    db: Session = Depends(get_db),
) -> StudyOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    studies_service.assign_project(
        db,
        study,
        project,
        tool_code=payload.tool_code,
        study_tool_id=payload.study_tool_id,
        label=payload.label,
    )
    db.refresh(study)
    study = studies_service.get_study(db, study_id)
    return _out(study)


@router.delete(
    "/{study_id}/projects/{project_id}",
    response_model=OkResponse,
    operation_id="unassignStudyProject",
)
def unassign_project(
    study_id: str,
    project_id: str,
    db: Session = Depends(get_db),
) -> OkResponse:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.study_id != study.id:
        raise HTTPException(status_code=400, detail="Project is not in this study")
    studies_service.unassign_project(db, project)
    return OkResponse(success=True)


def _view_def_out(row) -> TriangulationViewDefinitionOut:
    return TriangulationViewDefinitionOut(
        id=row.id,
        study_id=row.study_id,
        code=row.code,
        title=row.title,
        description=row.description,
        definition=row.definition if isinstance(row.definition, dict) else {},
    )


@router.get(
    "/{study_id}/triangulation-views",
    response_model=list[TriangulationViewDefinitionOut],
    operation_id="listStudyTriangulationViews",
)
def list_study_triangulation_views(
    study_id: str, db: Session = Depends(get_db)
) -> list[TriangulationViewDefinitionOut]:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return [_view_def_out(r) for r in tri_service.list_definition_rows(db, study_id)]


@router.post(
    "/{study_id}/triangulation-views",
    response_model=TriangulationViewDefinitionOut,
    operation_id="createStudyTriangulationView",
)
def create_study_triangulation_view(
    study_id: str,
    payload: TriangulationViewDefinitionCreate,
    db: Session = Depends(get_db),
) -> TriangulationViewDefinitionOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    code = payload.code.strip()
    if tri_service.get_view_row(db, study_id, code):
        raise HTTPException(status_code=400, detail=f"View code already exists: {code}")
    definition = dict(payload.definition or {})
    definition.setdefault("code", code)
    definition.setdefault("title", payload.title)
    if payload.description is not None:
        definition.setdefault("description", payload.description)
    row = tri_service.upsert_view(
        db,
        study_id,
        code=code,
        title=payload.title,
        description=payload.description,
        definition=definition,
    )
    return _view_def_out(row)


@router.get(
    "/{study_id}/triangulation-views/{code}",
    response_model=TriangulationViewDefinitionOut,
    operation_id="getStudyTriangulationView",
)
def get_study_triangulation_view(
    study_id: str, code: str, db: Session = Depends(get_db)
) -> TriangulationViewDefinitionOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    row = tri_service.get_view_row(db, study_id, code)
    if not row:
        raise HTTPException(status_code=404, detail="Triangulation view not found")
    return _view_def_out(row)


@router.put(
    "/{study_id}/triangulation-views/{code}",
    response_model=TriangulationViewDefinitionOut,
    operation_id="updateStudyTriangulationView",
)
def update_study_triangulation_view(
    study_id: str,
    code: str,
    payload: TriangulationViewDefinitionUpdate,
    db: Session = Depends(get_db),
) -> TriangulationViewDefinitionOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    row = tri_service.get_view_row(db, study_id, code)
    if not row:
        raise HTTPException(status_code=404, detail="Triangulation view not found")
    new_code = (payload.code or row.code).strip()
    if new_code != row.code and tri_service.get_view_row(db, study_id, new_code):
        raise HTTPException(status_code=400, detail=f"View code already exists: {new_code}")
    definition = (
        dict(payload.definition)
        if payload.definition is not None
        else (row.definition if isinstance(row.definition, dict) else {})
    )
    title = payload.title if payload.title is not None else row.title
    description = (
        payload.description if "description" in payload.model_fields_set else row.description
    )
    row = tri_service.upsert_view(
        db,
        study_id,
        code=new_code,
        title=title,
        description=description,
        definition=definition,
        view_id=row.id,
    )
    return _view_def_out(row)


@router.delete(
    "/{study_id}/triangulation-views/{code}",
    response_model=OkResponse,
    operation_id="deleteStudyTriangulationView",
)
def delete_study_triangulation_view(
    study_id: str, code: str, db: Session = Depends(get_db)
) -> OkResponse:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    row = tri_service.get_view_row(db, study_id, code)
    if not row:
        raise HTTPException(status_code=404, detail="Triangulation view not found")
    tri_service.delete_view(db, row)
    return OkResponse(success=True)
