"""Filesystem paths for generated report PDF/DOCX/ExecuteResult artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "data" / "reports"


def reports_dir() -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORTS_DIR


def pdf_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.pdf"


def docx_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.docx"


def result_json_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.json"


def write_report_result(report_id: str, result: Any) -> str:
    """Write ExecuteResult JSON under data/reports/; return relative result_ref."""
    path = result_json_path_for(report_id)
    path.write_text(json.dumps(result, default=str), encoding="utf-8")
    return f"data/reports/{report_id}.json"


def read_report_result(result_ref: str) -> Any:
    path = Path(result_ref)
    if not path.is_absolute():
        path = _REPO_ROOT / result_ref
    return json.loads(path.read_text(encoding="utf-8"))
