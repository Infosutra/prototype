"""Filesystem paths for generated report PDF/DOCX artifacts."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_REPORTS_DIR = _REPO_ROOT / "data" / "reports"


def reports_dir() -> Path:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORTS_DIR


def pdf_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.pdf"


def docx_path_for(report_id: str) -> Path:
    return reports_dir() / f"{report_id}.docx"
