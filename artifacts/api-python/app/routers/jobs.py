"""Job enqueue / status API. HTTP is thin: enqueue or hydrate status only."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Study
from app.db.session import get_db
from app.schemas.jobs import JobCreate, JobCreated, JobStatusOut
from app.services.jobs import store

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobCreated,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createJob",
)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> JobCreated:
    if payload.study_id is not None and db.get(Study, payload.study_id) is None:
        raise HTTPException(status_code=404, detail="Study not found")
    job = store.enqueue(
        db,
        job_type=payload.type,
        payload=payload.payload or {},
        study_id=payload.study_id,
    )
    return JobCreated(job_id=job.id)


@router.get("/{job_id}", response_model=JobStatusOut, operation_id="getJob")
def get_job(job_id: str, db: Session = Depends(get_db)) -> JobStatusOut:
    data = store.get_for_api(db, job_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Job not found")
    study_id = data.get("studyId")
    if study_id is not None and db.get(Study, study_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusOut(
        job_id=data["jobId"],
        type=data["type"],
        status=data["status"],
        study_id=study_id,
        result=data.get("result"),
        error=data.get("error"),
    )
