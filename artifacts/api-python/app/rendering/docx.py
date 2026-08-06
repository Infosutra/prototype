"""DOCX export for DQA Daily & Final reports."""

from __future__ import annotations

from typing import Any

from app.rendering.daily_docx import render_daily_docx
from app.rendering.final_docx import render_final_docx


def render_report_docx(report_type: str | None, stats: dict[str, Any]) -> bytes:
    if report_type == "final_dqa":
        return render_final_docx(stats)
    return render_daily_docx(stats)


__all__ = ["render_daily_docx", "render_final_docx", "render_report_docx"]
