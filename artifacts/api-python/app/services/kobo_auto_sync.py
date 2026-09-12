"""Periodic Kobo sync for the workspace active study."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import structlog
from sqlalchemy.orm import Session

from app.db.models import Study
from app.services.kobo_sync import try_sync_all_projects
from app.services.settings import get_or_create_settings

logger = structlog.stdlib.get_logger(__name__)

_last_auto_sync_at: float | None = None


def _interval_minutes() -> int:
    raw = os.environ.get("KOBO_AUTO_SYNC_INTERVAL_MINUTES", "30").strip()
    try:
        value = int(raw)
    except ValueError:
        return 30
    return max(0, value)


def maybe_run_scheduled_kobo_sync(db: Session) -> bool:
    """Run active-study sync when the interval has elapsed. Returns True if a sync ran."""
    global _last_auto_sync_at

    interval = _interval_minutes()
    if interval <= 0:
        return False

    now = time.monotonic()
    if _last_auto_sync_at is not None and (now - _last_auto_sync_at) < interval * 60:
        return False

    settings = get_or_create_settings(db)
    study_id = settings.active_study_id
    if not study_id:
        logger.info("auto_sync_skipped", reason="no_active_study")
        _last_auto_sync_at = now
        return False

    if db.get(Study, study_id) is None:
        logger.info("auto_sync_skipped", reason="active_study_missing", study_id=study_id)
        _last_auto_sync_at = now
        return False

    logger.info(
        "auto_sync_started",
        study_id=study_id,
        interval_minutes=interval,
        at=datetime.now(timezone.utc).isoformat(),
    )
    result = try_sync_all_projects(db, study_id)
    if result is None:
        # Busy — do not advance the interval clock so we retry soon.
        return False

    _last_auto_sync_at = now
    logger.info(
        "auto_sync_complete",
        study_id=study_id,
        success=result.get("success"),
        projects_synced=result.get("projects_synced"),
        errors=len(result.get("errors") or []),
    )
    return True


def reset_auto_sync_clock_for_tests() -> None:
    """Test helper to clear the in-memory interval gate."""
    global _last_auto_sync_at
    _last_auto_sync_at = None
