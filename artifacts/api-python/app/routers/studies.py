from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Project
from app.db.session import get_db
from app.schemas.studies import StudyAssignProject, StudyCreate, StudyOut, StudyUpdate
from app.services import studies as studies_service

router = APIRouter(prefix="/studies", tags=["studies"])


def _out(study) -> StudyOut:
    return StudyOut.model_validate(studies_service.study_to_dict(study))


@router.get("", response_model=list[StudyOut])
def list_studies(db: Session = Depends(get_db)) -> list[StudyOut]:
    return [StudyOut.model_validate(item) for item in studies_service.list_studies(db)]


@router.post("", response_model=StudyOut)
def create_study(payload: StudyCreate, db: Session = Depends(get_db)) -> StudyOut:
    study = studies_service.create_study(db, payload.model_dump(by_alias=False))
    return _out(study)


@router.get("/{study_id}", response_model=StudyOut)
def get_study(study_id: str, db: Session = Depends(get_db)) -> StudyOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    return _out(study)


@router.patch("/{study_id}", response_model=StudyOut)
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


@router.delete("/{study_id}")
def delete_study(study_id: str, db: Session = Depends(get_db)) -> dict:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    studies_service.delete_study(db, study)
    return {"success": True}


@router.post("/{study_id}/projects", response_model=StudyOut)
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
    studies_service.assign_project(db, study, project, tool_code=payload.tool_code)
    db.refresh(study)
    return _out(study)


@router.delete("/{study_id}/projects/{project_id}", response_model=StudyOut)
def unassign_project(
    study_id: str,
    project_id: str,
    db: Session = Depends(get_db),
) -> StudyOut:
    study = studies_service.get_study(db, study_id)
    if not study:
        raise HTTPException(status_code=404, detail="Study not found")
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.study_id != study.id:
        raise HTTPException(status_code=400, detail="Project is not in this study")
    studies_service.unassign_project(db, project)
    db.refresh(study)
    return _out(study)
