from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db.models import Project
from app.db.session import get_db
from app.integrations.kobo import KoboApiError
from app.schemas.common import OkResponse
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

router = APIRouter(prefix="/studies", tags=["studies"])


def _out(study) -> StudyOut:
    return StudyOut.model_validate(studies_service.study_to_dict(study))


@router.get("", response_model=list[StudyOut], operation_id="getStudies")
def list_studies(db: Session = Depends(get_db)) -> list[StudyOut]:
    return [StudyOut.model_validate(item) for item in studies_service.list_studies(db)]


@router.post("", response_model=StudyOut, operation_id="createStudy")
def create_study(payload: StudyCreate, db: Session = Depends(get_db)) -> StudyOut:
    study = studies_service.create_study(db, payload.model_dump(by_alias=False))
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
    study = studies_service.update_study(db, study, data)
    return _out(study)


@router.delete("/{study_id}", response_model=OkResponse, operation_id="deleteStudy")
def delete_study(study_id: str, db: Session = Depends(get_db)) -> OkResponse:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    studies_service.delete_study(db, study)
    return OkResponse(success=True)


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
