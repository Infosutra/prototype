"""Filesystem paths for job result JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# app/services/jobs/artifacts.py → repo root is parents[5]
# (report_storage lives one level up and uses parents[4])
_REPO_ROOT = Path(__file__).resolve().parents[5]
_JOBS_DIR = _REPO_ROOT / "data" / "jobs"


def jobs_dir() -> Path:
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return _JOBS_DIR


def job_result_path(job_id: str) -> Path:
    return jobs_dir() / f"{job_id}.json"


def write_job_result(job_id: str, result: Any) -> str:
    """Write result JSON; return relative result_ref (data/jobs/{id}.json)."""
    path = job_result_path(job_id)
    path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return f"data/jobs/{job_id}.json"


def read_job_result(result_ref: str) -> Any:
    """Load result from a result_ref path relative to repo root or absolute."""
    path = Path(result_ref)
    if not path.is_absolute():
        path = _REPO_ROOT / result_ref
    return json.loads(path.read_text(encoding="utf-8"))


def delete_job_result(job_id: str) -> None:
    path = job_result_path(job_id)
    if path.is_file():
        path.unlink()
