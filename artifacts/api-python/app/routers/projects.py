from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project
from app.db.session import get_db
from app.schemas.common import StudyIdQuery
from app.schemas.projects import ProjectOut, ProjectUpdate, SyncResult
from app.schemas.submissions import SubmissionGrid
from app.services import studies as studies_service
from app.services.form_labels import get_form_translations, resolve_label_language
from app.services.kobo_sync import sync_all_projects, sync_project
from app.services.projects import project_to_dict
from app.services.submission_grid import DEFAULT_LIMIT, MAX_LIMIT, build_submission_grid

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut], operation_id="getProjects")
def list_projects(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> list[ProjectOut]:
    query = (
        select(Project)
        .options(joinedload(Project.study), joinedload(Project.study_tool))
        .order_by(Project.name)
    )
    if q.study_id:
        query = query.where(Project.study_id == q.study_id)
    rows = db.scalars(query).unique().all()
    return [ProjectOut.model_validate(project_to_dict(row)) for row in rows]


@router.post("/sync", response_model=SyncResult, operation_id="syncProjects")
def sync_projects(
    q: Annotated[StudyIdQuery, Query()],
    db: Session = Depends(get_db),
) -> SyncResult:
    if not q.study_id:
        raise HTTPException(status_code=400, detail="studyId query parameter is required")
    try:
        result = sync_all_projects(db, q.study_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncResult.model_validate(result)


@router.get("/{project_id}", response_model=ProjectOut, operation_id="getProject")
def get_project(project_id: str, db: Session = Depends(get_db)) -> ProjectOut:
    project = db.scalars(
        select(Project)
        .options(joinedload(Project.study), joinedload(Project.study_tool))
        .where(Project.id == project_id)
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectOut.model_validate(project_to_dict(project))


@router.patch("/{project_id}", response_model=ProjectOut, operation_id="updateProject")
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
) -> ProjectOut:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    data = payload.model_dump(exclude_unset=True, by_alias=False)

    if "label_language" in data and data["label_language"] is not None:
        form_definition = (
            project.form_definition if isinstance(project.form_definition, dict) else None
        )
        available = get_form_translations(form_definition)
        resolved = resolve_label_language(data["label_language"], form_definition)
        if available and (
            not resolved
            or not any(lang.lower() == resolved.lower() for lang in available)
        ):
            raise HTTPException(
                status_code=400,
                detail=f"labelLanguage must be one of: {', '.join(available)}",
            )
        project.label_language = resolved or str(data["label_language"]).strip()

    if "study_id" in data:
        study_id = data["study_id"]
        if study_id is None or study_id == "":
            studies_service.unassign_project(db, project)
        else:
            study = studies_service.get_study(db, study_id)
            if not study:
                raise HTTPException(status_code=404, detail="Study not found")
            tool = data.get("tool_code") if "tool_code" in data else project.tool_code
            study_tool_id = data.get("study_tool_id") if "study_tool_id" in data else project.study_tool_id
            studies_service.assign_project(
                db, study, project, tool_code=tool, study_tool_id=study_tool_id
            )
    elif "tool_code" in data or "study_tool_id" in data:
        if not project.study_id:
            raise HTTPException(
                status_code=400,
                detail="Assign the project to a study before setting a tool code",
            )
        study = studies_service.get_study(db, project.study_id)
        if not study:
            raise HTTPException(status_code=404, detail="Study not found")
        studies_service.assign_project(
            db,
            study,
            project,
            tool_code=data.get("tool_code"),
            study_tool_id=data.get("study_tool_id"),
        )
    else:
        db.commit()

    project = db.scalars(
        select(Project)
        .options(joinedload(Project.study), joinedload(Project.study_tool))
        .where(Project.id == project_id)
    ).first()
    return ProjectOut.model_validate(project_to_dict(project))


@router.get("/{project_id}/data-grid", response_model=SubmissionGrid, operation_id="getProjectDataGrid")
def project_data_grid(
    project_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    severity: str | None = Query(default=None),
    enumerator: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> SubmissionGrid:
    """All submissions of a project as rows x questions, with DQA severity per cell."""
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    grid = build_submission_grid(
        db,
        project,
        page=page,
        limit=limit,
        severity=severity,
        enumerator=enumerator,
    )
    return SubmissionGrid.model_validate(grid)


@router.post("/{project_id}/sync", response_model=SyncResult, operation_id="syncProject")
def sync_one_project(project_id: str, db: Session = Depends(get_db)) -> SyncResult:
    try:
        result = sync_project(db, project_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SyncResult.model_validate(result)
