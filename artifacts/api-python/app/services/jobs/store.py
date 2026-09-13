"""Job store: enqueue / claim / complete / fail.

Claim strategy (single-process): UPDATE … WHERE status='pending' to
'processing', then run the handler. Prefer a small per-tick claim budget in
the lifespan scheduler so long execute jobs do not starve Kobo/email ticks.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Job
from app.services.jobs import artifacts

logger = structlog.stdlib.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(
    db: Session,
    *,
    job_type: str,
    payload: dict[str, Any] | None = None,
    study_id: str | None = None,
    expires_at: datetime | None = None,
    commit: bool = True,
) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        type=job_type,
        status="pending",
        study_id=study_id,
        payload=payload or {},
        created_at=_now(),
        updated_at=_now(),
        expires_at=expires_at,
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def get(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def claim(db: Session, *, limit: int = 1) -> list[Job]:
    """Claim up to ``limit`` pending jobs (pending → processing).

    Uses a SELECT of pending ids then a conditional UPDATE so SQLite stays
    simple under a single API process. Returns the claimed Job rows.
    """
    if limit <= 0:
        return []
    pending_ids = list(
        db.scalars(
            select(Job.id)
            .where(Job.status == "pending")
            .order_by(Job.created_at.asc())
            .limit(limit)
        ).all()
    )
    if not pending_ids:
        return []

    now = _now()
    claimed: list[Job] = []
    for job_id in pending_ids:
        result = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "pending")
            .values(status="processing", started_at=now, updated_at=now)
        )
        if result.rowcount:
            job = db.get(Job, job_id)
            if job is not None:
                claimed.append(job)
    if claimed:
        db.commit()
        for job in claimed:
            db.refresh(job)
    return claimed


def fail_orphaned_processing(
    db: Session,
    *,
    error: str = "Interrupted by server restart",
) -> int:
    """Mark in-flight jobs failed. Safe after process restart (in-process worker)."""
    rows = list(db.scalars(select(Job).where(Job.status == "processing")).all())
    for job in rows:
        fail(db, job, error, commit=False)
    if rows:
        db.commit()
        logger.info("jobs_orphaned_failed", count=len(rows))
    return len(rows)


def complete(
    db: Session,
    job: Job,
    result: Any,
    *,
    commit: bool = True,
) -> Job:
    """Write result file, set result_ref, mark completed. No result column."""
    ref = artifacts.write_job_result(job.id, result)
    job.result_ref = ref
    job.status = "completed"
    job.error = None
    job.finished_at = _now()
    job.updated_at = job.finished_at
    if commit:
        db.commit()
        db.refresh(job)
    return job


def fail(
    db: Session,
    job: Job,
    error: str,
    *,
    commit: bool = True,
) -> Job:
    """Mark failed with a domain error message; leave result_ref null."""
    job.status = "failed"
    job.error = error
    job.result_ref = None
    job.finished_at = _now()
    job.updated_at = job.finished_at
    if commit:
        db.commit()
        db.refresh(job)
    return job


def get_for_api(db: Session, job_id: str) -> dict[str, Any] | None:
    """API payload: hydrate ``result`` from file; never expose ``result_ref``."""
    job = get(db, job_id)
    if job is None:
        return None

    out: dict[str, Any] = {
        "jobId": job.id,
        "type": job.type,
        "status": job.status,
        "studyId": job.study_id,
    }
    if job.status == "failed":
        out["error"] = job.error or "Job failed"
        return out

    if job.status == "completed":
        if not job.result_ref:
            out["status"] = "failed"
            out["error"] = "Job completed but result is missing"
            return out
        try:
            out["result"] = artifacts.read_job_result(job.result_ref)
        except Exception:
            logger.exception("job_result_hydrate_failed", job_id=job.id)
            out["status"] = "failed"
            out["error"] = "Job result could not be loaded"
            return out
    return out
