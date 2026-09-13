from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project, Study, Submission
from app.db.session import SessionLocal
from app.integrations.kobo import (
    KoboClient,
    get_asset_name,
    get_asset_status,
)
from app.services.form_labels import (
    build_enumerator_canonical_map,
    extract_enumerator_name,
)
from app.services.settings import get_kobo_token_from_credential, get_study_credential

logger = structlog.stdlib.get_logger(__name__)

# SQLite allows one writer at a time. Parallel sync overlaps Kobo HTTP, then
# serializes all ORM writes through this lock.
_SYNC_DB_LOCK = threading.Lock()
# One full study/form sync at a time (manual, auto, activate, pre-mail).
_SYNC_RUN_LOCK = threading.Lock()

META_QUESTION_TYPES = {
    "start",
    "end",
    "begin_group",
    "end_group",
    "begin_repeat",
    "end_repeat",
    "calculate",
    "note",
}

# Daily full ID reconcile is due at/after this local time (study timezone).
FULL_RECONCILE_LOCAL_TIME = dt_time(18, 0)


def _prune_missing_submissions(
    db: Session,
    project_id: str,
    remote_ids: set[str],
) -> int:
    """Hard-delete local submissions that no longer exist on Kobo.

    DQA flags cascade via FK. Only call after a successful full remote ID inventory.
    """
    local_ids = {
        row[0]
        for row in db.execute(
            select(Submission.kobo_id).where(Submission.project_id == project_id)
        ).all()
    }
    orphan_ids = local_ids - remote_ids
    if not orphan_ids:
        return 0
    result = db.execute(
        delete(Submission).where(
            Submission.project_id == project_id,
            Submission.kobo_id.in_(orphan_ids),
        )
    )
    return int(result.rowcount or 0)


def _as_date(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        # Support Z suffix
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _metadata_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        parts = [t for t in (_metadata_text(v) for v in value) if t]
        return ", ".join(dict.fromkeys(parts)) if parts else None
    if isinstance(value, dict):
        return _metadata_text(value.get("label")) or _metadata_text(value.get("value"))
    return None


def _count_questions(content: dict[str, Any] | None) -> int:
    survey = (content or {}).get("survey")
    if not isinstance(survey, list):
        return 0
    count = 0
    for item in survey:
        if not isinstance(item, dict):
            continue
        qtype = item.get("type")
        if isinstance(qtype, str) and qtype not in META_QUESTION_TYPES:
            count += 1
    return count


def _submission_location(submission: dict[str, Any]) -> str | None:
    value = submission.get("_geolocation")
    if isinstance(value, list) and len(value) >= 2:
        lat, lng = value[0], value[1]
        if lat is not None and lng is not None:
            return f"{lat}, {lng}"
    if isinstance(value, str) and value:
        return value
    return None


def _coerce_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return None


def _remote_submission_count(*sources: dict[str, Any] | None) -> int | None:
    """Best-effort Kobo deployment submission count from asset payloads."""
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("deployment__submission_count", "submission_count"):
            count = _coerce_count(source.get(key))
            if count is not None:
                return count
        summary = source.get("summary")
        if isinstance(summary, dict):
            for key in ("submission_count", "submissions", "count"):
                count = _coerce_count(summary.get(key))
                if count is not None:
                    return count
    return None


def _study_zone(tz_name: str | None) -> ZoneInfo:
    name = (tz_name or "").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        logger.warning("unknown_study_timezone", timezone=tz_name, fallback="UTC")
        return ZoneInfo("UTC")


def _daily_reconcile_anchor(now_utc: datetime, tz_name: str | None) -> datetime:
    """Most recent 18:00 in the study timezone that has already started (as naive UTC)."""
    zone = _study_zone(tz_name)
    aware_now = now_utc if now_utc.tzinfo else now_utc.replace(tzinfo=timezone.utc)
    local_now = aware_now.astimezone(zone)
    anchor_local = datetime.combine(local_now.date(), FULL_RECONCILE_LOCAL_TIME, tzinfo=zone)
    if local_now < anchor_local:
        anchor_local = anchor_local - timedelta(days=1)
    return anchor_local.astimezone(timezone.utc).replace(tzinfo=None)


def _full_reconcile_due(
    *,
    last_full_reconcile_at: datetime | None,
    now_utc: datetime,
    study_timezone: str | None,
) -> bool:
    """True when a Sync after the daily 18:00 window has not yet reconciled today."""
    anchor = _daily_reconcile_anchor(now_utc, study_timezone)
    last = _naive_utc(last_full_reconcile_at)
    return last is None or last < anchor


def refresh_submission_enumerators(
    db: Session,
    *,
    project_ids: list[str],
    projects_by_id: dict[str, Project] | None = None,
    submission_ids: set[str] | None = None,
    reextract: bool = True,
    canonicalize: bool = True,
) -> int:
    """Re-extract and/or canonicalize enumerator names for submissions in scope."""
    if not project_ids:
        return 0
    projects_by_id = projects_by_id or {
        p.id: p
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    updated = 0

    if reextract:
        if submission_ids is not None and not submission_ids:
            pass
        else:
            query = select(Submission).where(Submission.project_id.in_(project_ids))
            if submission_ids is not None:
                query = query.where(Submission.id.in_(submission_ids))
            for row in db.scalars(query).all():
                project = projects_by_id.get(row.project_id)
                form_definition = (
                    project.form_definition
                    if project and isinstance(project.form_definition, dict)
                    else None
                )
                data = row.data if isinstance(row.data, dict) else {}
                derived = extract_enumerator_name(data, form_definition) or (
                    data.get("_submitted_by") if isinstance(data, dict) else None
                ) or "Unknown"
                derived = str(derived).strip() or "Unknown"
                if derived != (row.enumerator or ""):
                    row.enumerator = derived
                    updated += 1

    if canonicalize:
        all_rows = list(
            db.scalars(
                select(Submission).where(Submission.project_id.in_(project_ids))
            ).all()
        )
        name_counts: dict[str, int] = {}
        for row in all_rows:
            name = (row.enumerator or "").strip()
            if name:
                name_counts[name] = name_counts.get(name, 0) + 1
        canonical = build_enumerator_canonical_map(
            list(name_counts.keys()), counts=name_counts
        )
        for row in all_rows:
            mapped = canonical.get(row.enumerator or "")
            if mapped and mapped != row.enumerator:
                row.enumerator = mapped
                updated += 1

    for pid in project_ids:
        project = projects_by_id.get(pid)
        if not project:
            continue
        enumerator_count = db.scalar(
            select(func.count(distinct(Submission.enumerator))).where(
                Submission.project_id == pid
            )
        ) or 0
        project.enumerator_count = int(enumerator_count)

    return updated


def _configured_client(db: Session, study_id: str) -> KoboClient:
    cred = get_study_credential(db, study_id)
    if not cred:
        raise ValueError(
            "KoboToolbox is not configured for this study. "
            "Add a server URL and API token on the study's Kobo settings.",
        )
    token = get_kobo_token_from_credential(cred)
    if not cred.kobo_server_url or not token:
        raise ValueError(
            "KoboToolbox is not configured for this study. "
            "Add a server URL and API token on the study's Kobo settings.",
        )
    return KoboClient(cred.kobo_server_url, token)


def _run_dqa_for_touched(db: Session, project_id: str, touched_ids: set[str]) -> None:
    if not touched_ids:
        return
    try:
        from app.services import dqa_engine

        dqa_engine.evaluate_project(db, project_id, submission_ids=touched_ids)
    except Exception:
        logger.exception("dqa_evaluation_failed", project_id=project_id)


def _sync_asset(
    db: Session,
    client: KoboClient,
    asset_summary: dict[str, Any],
    *,
    study_id: str | None = None,
    study_timezone: str | None = None,
    run_post_hooks: bool = True,
    canonicalize_enumerators: bool = True,
    prefetched: dict[str, Any] | None = None,
) -> dict[str, Any]:
    phase_ms: dict[str, float] = {}
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    uid = str(asset_summary["uid"])
    previous = db.get(Project, uid)

    project = previous or Project(id=uid, uid=uid, name=get_asset_name(asset_summary))
    project.name = get_asset_name(asset_summary)
    project.description = _metadata_text((asset_summary.get("settings") or {}).get("description"))
    project.status = get_asset_status(asset_summary)
    project.asset_type = asset_summary.get("asset_type") or "survey"
    project.form_version_id = asset_summary.get("version_id")
    project.deployed_version_id = asset_summary.get("deployed_version_id")
    project.kobo_date_modified = _as_date(asset_summary.get("date_modified"))
    project.deployed_at = _as_date(asset_summary.get("date_deployed"))
    project.sync_status = "syncing"
    project.sync_error = None
    project.sector = _metadata_text((asset_summary.get("settings") or {}).get("sector"))
    project.country = _metadata_text((asset_summary.get("settings") or {}).get("country"))
    project.updated_at = now
    if study_id and (previous is None or not project.study_id or project.study_id == study_id):
        project.study_id = study_id
    if previous is None:
        db.add(project)
    db.flush()

    if prefetched is not None:
        asset = prefetched["asset"]
        versions = prefetched["versions"]
        submissions = list(prefetched.get("submissions") or [])
        phase_ms["metadata"] = float(prefetched.get("phase_ms", {}).get("metadata") or 0.0)
        phase_ms["delta_fetch"] = float(prefetched.get("phase_ms", {}).get("delta_fetch") or 0.0)
    else:
        t_meta = time.perf_counter()
        asset = client.get_asset(uid)
        versions = client.list_versions(uid)
        phase_ms["metadata"] = (time.perf_counter() - t_meta) * 1000.0

    current_version_number = asset.get("version_count") or len(versions)
    deployed_version_id = asset.get("deployed_version_id")
    deployed_version_number = None
    if deployed_version_id:
        for index, version in enumerate(versions):
            if version.get("uid") == deployed_version_id:
                deployed_version_number = len(versions) - index
                break

    project.name = get_asset_name(asset)
    project.description = _metadata_text((asset.get("settings") or {}).get("description"))
    project.question_count = _count_questions(asset.get("content") if isinstance(asset.get("content"), dict) else None)
    project.owner = (
        _metadata_text(asset.get("owner_label"))
        or _metadata_text(asset.get("owner__username"))
        or _metadata_text(asset.get("created_by"))
    )
    project.last_edited_by = _metadata_text(asset.get("last_modified_by"))
    project.current_version_number = int(current_version_number)
    project.deployed_version_number = deployed_version_number
    project.form_definition = asset.get("content") if isinstance(asset.get("content"), dict) else None
    project.form_version_id = asset.get("version_id") or asset_summary.get("version_id")
    project.deployed_version_id = deployed_version_id or asset_summary.get("deployed_version_id")
    project.kobo_date_modified = _as_date(asset.get("date_modified"))
    project.sector = _metadata_text((asset.get("settings") or {}).get("sector"))
    project.country = _metadata_text((asset.get("settings") or {}).get("country"))
    db.flush()

    if study_timezone is None and project.study_id:
        study = db.get(Study, project.study_id)
        study_timezone = study.timezone if study else None

    status = get_asset_status(asset)
    # Watermark must be the latest *submission* time, not wall-clock sync time.
    # Using sync-time caused later incremental queries to skip submissions that
    # arrived after the previous fetch but before the sync finished.
    watermark_dt = _naive_utc(previous.last_submission_at) if previous else None
    watermark = watermark_dt.isoformat() if watermark_dt else None
    if watermark and not watermark.endswith("Z") and "+" not in watermark:
        watermark = f"{watermark}Z"

    if prefetched is None:
        t_fetch = time.perf_counter()
        submissions = [] if status == "draft" else client.list_submissions(uid, modified_after=watermark)
        phase_ms["delta_fetch"] = (time.perf_counter() - t_fetch) * 1000.0
    elif status == "draft":
        submissions = []

    existing_ids = {
        row[0]
        for row in db.execute(
            select(Submission.kobo_id).where(Submission.project_id == uid)
        ).all()
    }

    new_submissions = 0
    deleted_submissions = 0
    touched_submission_ids: set[str] = set()
    latest_submission_at = _naive_utc(previous.last_submission_at) if previous else None
    form_definition = project.form_definition if isinstance(project.form_definition, dict) else None

    t_upsert = time.perf_counter()
    for submission in submissions:
        kobo_id = str(submission.get("_id") or submission.get("_uuid") or "")
        if not kobo_id:
            continue
        submitted_at = _naive_utc(
            _as_date(submission.get("_submission_time"))
            or _as_date(submission.get("_date_modified"))
            or now
        )
        if latest_submission_at is None or (submitted_at and submitted_at > latest_submission_at):
            latest_submission_at = submitted_at
        if kobo_id not in existing_ids:
            new_submissions += 1

        enumerator = extract_enumerator_name(submission, form_definition) or (
            submission.get("_submitted_by") or "Unknown"
        )
        status_value = "validated" if submission.get("_status") == "submitted_via_web" else "pending"

        row_id = f"{uid}:{kobo_id}"
        row = db.get(Submission, row_id)
        if row is None:
            row = Submission(id=row_id, kobo_id=kobo_id, project_id=uid)
            db.add(row)

        row.uuid = submission.get("_uuid")
        row.form_id = uid
        row.form_name = get_asset_name(asset)
        row.enumerator = str(enumerator)
        row.status = status_value
        row.submitted_at = submitted_at
        edited = _naive_utc(_as_date(submission.get("_date_modified")))
        row.edited_at = edited
        row.location = _submission_location(submission)
        row.data = submission
        row.attachment_count = (
            len(submission["_attachments"])
            if isinstance(submission.get("_attachments"), list)
            else 0
        )
        touched_submission_ids.add(row_id)

    db.flush()
    phase_ms["db_write"] = (time.perf_counter() - t_upsert) * 1000.0

    # Incremental upsert cannot observe deletes. Run a full remote ID inventory
    # when counts diverge, on first sync, or after the daily 18:00 study-local window.
    reconciled = False
    if status != "draft":
        local_count_before_prune = db.scalar(
            select(func.count()).select_from(Submission).where(Submission.project_id == uid)
        ) or 0
        remote_count = _remote_submission_count(asset, asset_summary)
        count_mismatch = remote_count is None or remote_count != int(local_count_before_prune)
        daily_due = _full_reconcile_due(
            last_full_reconcile_at=previous.last_full_reconcile_at if previous else None,
            now_utc=now,
            study_timezone=study_timezone,
        )
        # First sync (no watermark) already downloaded every payload; reuse those IDs.
        first_full_fetch = watermark is None

        t_ids = time.perf_counter()
        if first_full_fetch and submissions:
            remote_ids = {
                str(item.get("_id")).strip()
                for item in submissions
                if item.get("_id") is not None and str(item.get("_id")).strip()
            }
            deleted_submissions = _prune_missing_submissions(db, uid, remote_ids)
            reconciled = True
            logger.info(
                "reconcile_submissions",
                project=uid,
                source="delta_ids",
                deleted=deleted_submissions,
                remote_count=remote_count,
                local_count=local_count_before_prune,
            )
        elif count_mismatch or daily_due or previous is None:
            remote_ids = client.list_submission_ids(uid)
            deleted_submissions = _prune_missing_submissions(db, uid, remote_ids)
            reconciled = True
            reason = (
                "count_mismatch"
                if count_mismatch
                else ("daily_18h" if daily_due else "first_sync")
            )
            logger.info(
                "reconcile_submissions",
                project=uid,
                source="list_submission_ids",
                reason=reason,
                deleted=deleted_submissions,
                remote_count=remote_count,
                local_count=local_count_before_prune,
            )
        else:
            logger.info(
                "reconcile_skipped",
                project=uid,
                remote_count=remote_count,
                local_count=local_count_before_prune,
            )
        phase_ms["id_reconcile"] = (time.perf_counter() - t_ids) * 1000.0
        if deleted_submissions:
            db.flush()
        if reconciled:
            project.last_full_reconcile_at = _naive_utc(now)
    else:
        phase_ms["id_reconcile"] = 0.0

    t_enum = time.perf_counter()
    refreshed_enumerators = 0
    if touched_submission_ids:
        refreshed_enumerators = refresh_submission_enumerators(
            db,
            project_ids=[uid],
            projects_by_id={uid: project},
            submission_ids=touched_submission_ids,
            reextract=True,
            canonicalize=canonicalize_enumerators,
        )
        if refreshed_enumerators:
            logger.info(
                "enumerators_refreshed",
                project=uid,
                refreshed=refreshed_enumerators,
            )
            db.flush()
    phase_ms["enumerators"] = (time.perf_counter() - t_enum) * 1000.0

    # Dual-write reporting projections (answers + duration + calendar_day + study_id).
    if touched_submission_ids:
        from app.services.reporting.answers import replace_answers_for_submission

        for sid in touched_submission_ids:
            row = db.get(Submission, sid)
            if row is None:
                continue
            replace_answers_for_submission(
                db,
                row,
                project=project,
                study_timezone=study_timezone,
            )
        db.flush()

    submission_count = db.scalar(
        select(func.count()).select_from(Submission).where(Submission.project_id == uid)
    ) or 0
    enumerator_count = db.scalar(
        select(func.count(distinct(Submission.enumerator))).where(Submission.project_id == uid)
    ) or 0

    project.status = status
    project.submission_count = int(submission_count)
    project.enumerator_count = int(enumerator_count)
    project.form_count = 1
    project.last_submission_at = latest_submission_at
    project.last_sync_at = _naive_utc(now)
    # Keep watermark aligned with the newest submission we have stored.
    project.sync_watermark = project.last_submission_at
    project.sync_status = "success"
    project.sync_error = None
    project.updated_at = _naive_utc(now)
    db.commit()

    t_dqa = time.perf_counter()
    if run_post_hooks:
        try:
            from app.services import studies as studies_service

            studies_service.apply_all_study_form_maps(db)
        except Exception:
            logger.exception("study_tool_assignment_failed", project=uid, phase="after_sync")

        _run_dqa_for_touched(db, uid, touched_submission_ids)
    phase_ms["dqa"] = (time.perf_counter() - t_dqa) * 1000.0
    phase_ms["total"] = (time.perf_counter() - t0) * 1000.0

    logger.info(
        "sync_asset",
        project=uid,
        fetched=len(submissions),
        new=new_submissions,
        deleted=deleted_submissions,
        reconciled=reconciled,
        phase_ms={
            "metadata": round(phase_ms.get("metadata", 0.0), 1),
            "delta_fetch": round(phase_ms.get("delta_fetch", 0.0), 1),
            "db_write": round(phase_ms.get("db_write", 0.0), 1),
            "id_reconcile": round(phase_ms.get("id_reconcile", 0.0), 1),
            "enumerators": round(phase_ms.get("enumerators", 0.0), 1),
            "dqa": round(phase_ms.get("dqa", 0.0), 1),
            "total": round(phase_ms.get("total", 0.0), 1),
        },
    )

    return {
        "project_id": uid,
        "submissions_fetched": len(submissions),
        "new_submissions": new_submissions,
        "deleted_submissions": deleted_submissions,
        "touched_submission_ids": touched_submission_ids,
        "reconciled": reconciled,
        "phase_ms": {
            "metadata": round(phase_ms.get("metadata", 0.0), 1),
            "delta_fetch": round(phase_ms.get("delta_fetch", 0.0), 1),
            "db_write": round(phase_ms.get("db_write", 0.0), 1),
            "id_reconcile": round(phase_ms.get("id_reconcile", 0.0), 1),
            "enumerators": round(phase_ms.get("enumerators", 0.0), 1),
            "dqa": round(phase_ms.get("dqa", 0.0), 1),
            "total": round(phase_ms.get("total", 0.0), 1),
        },
    }


def _canonicalize_study_enumerators(db: Session, study_id: str) -> None:
    project_ids = list(
        db.scalars(select(Project.id).where(Project.study_id == study_id)).all()
    )
    if not project_ids:
        return
    projects_by_id = {
        p.id: p
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    updated = refresh_submission_enumerators(
        db,
        project_ids=project_ids,
        projects_by_id=projects_by_id,
        submission_ids=None,
        reextract=False,
        canonicalize=True,
    )
    if updated:
        logger.info(
            "enumerators_canonicalized",
            study=study_id,
            updated=updated,
        )
        db.commit()


def _sync_concurrency() -> int:
    raw = (os.environ.get("KOBO_SYNC_CONCURRENCY") or "4").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 4
    return max(1, min(8, value))


def _read_submission_watermark(uid: str) -> str | None:
    """Short locked read so parallel workers can fetch Kobo deltas without writing."""
    with _SYNC_DB_LOCK:
        db = SessionLocal()
        try:
            previous = db.get(Project, uid)
            watermark_dt = _naive_utc(previous.last_submission_at) if previous else None
            watermark = watermark_dt.isoformat() if watermark_dt else None
            if watermark and not watermark.endswith("Z") and "+" not in watermark:
                watermark = f"{watermark}Z"
            return watermark
        finally:
            db.close()


def _prefetch_asset_from_kobo(
    client: KoboClient,
    asset_summary: dict[str, Any],
) -> dict[str, Any]:
    """Network-only fetch (safe to run concurrently across forms)."""
    uid = str(asset_summary["uid"])
    watermark = _read_submission_watermark(uid)

    t_meta = time.perf_counter()
    asset = client.get_asset(uid)
    versions = client.list_versions(uid)
    metadata_ms = (time.perf_counter() - t_meta) * 1000.0

    status = get_asset_status(asset)
    t_fetch = time.perf_counter()
    submissions = (
        []
        if status == "draft"
        else client.list_submissions(uid, modified_after=watermark)
    )
    delta_fetch_ms = (time.perf_counter() - t_fetch) * 1000.0

    return {
        "asset": asset,
        "versions": versions,
        "submissions": submissions,
        "phase_ms": {
            "metadata": metadata_ms,
            "delta_fetch": delta_fetch_ms,
        },
    }


def _mark_asset_sync_failed(uid: str, message: str) -> None:
    if not uid:
        return
    with _SYNC_DB_LOCK:
        db = SessionLocal()
        try:
            project = db.get(Project, uid)
            if not project:
                return
            project.sync_status = "failed"
            project.sync_error = message[:1000]
            project.last_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
            project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
        except Exception:
            logger.exception("asset_sync_failure_persist_failed", asset_uid=uid)
            db.rollback()
        finally:
            db.close()


def _sync_one_asset_worker(
    *,
    client: KoboClient,
    asset: dict[str, Any],
    study_id: str,
    study_timezone: str | None,
) -> dict[str, Any]:
    """Prefetch from Kobo in parallel, then apply DB writes under a process lock."""
    name = get_asset_name(asset)
    uid = str(asset.get("uid") or "")

    try:
        prefetched = _prefetch_asset_from_kobo(client, asset)
    except Exception as exc:
        message = str(exc)
        logger.exception("asset_sync_failed", asset_uid=uid or None, phase="prefetch")
        _mark_asset_sync_failed(uid, message)
        return {
            "ok": False,
            "asset_uid": uid,
            "asset_name": name,
            "error": message,
        }

    with _SYNC_DB_LOCK:
        db = SessionLocal()
        try:
            result = _sync_asset(
                db,
                client,
                asset,
                study_id=study_id,
                study_timezone=study_timezone,
                run_post_hooks=False,
                canonicalize_enumerators=False,
                prefetched=prefetched,
            )
            return {
                "ok": True,
                "asset_uid": uid,
                "asset_name": name,
                "result": result,
            }
        except Exception as exc:
            message = str(exc)
            logger.exception("asset_sync_failed", asset_uid=uid or None, phase="persist")
            try:
                db.rollback()
                project = db.get(Project, uid) if uid else None
                if project:
                    project.sync_status = "failed"
                    project.sync_error = message[:1000]
                    project.last_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.commit()
            except Exception:
                logger.exception("asset_sync_failure_persist_failed", asset_uid=uid or None)
                db.rollback()
            return {
                "ok": False,
                "asset_uid": uid,
                "asset_name": name,
                "error": message,
            }
        finally:
            db.close()


def _seconds(ms: float) -> float:
    """Round milliseconds to seconds (1 decimal; 2 decimals when under 1s)."""
    seconds = ms / 1000.0
    if seconds == 0:
        return 0.0
    if seconds < 1.0:
        return round(seconds, 2)
    return round(seconds, 1)


def _slowest_form_s(phase_lists: list[dict[str, float]]) -> dict[str, float]:
    """Per-stage max across forms, in seconds (bottleneck signal under parallelism)."""
    mapping = (
        ("metadata", "kobo_metadata"),
        ("delta_fetch", "kobo_delta_fetch"),
        ("db_write", "db_write"),
    )
    peaked_ms = {src: 0.0 for src, _dst in mapping}
    for phases in phase_lists:
        for src, _dst in mapping:
            value = float(phases.get(src) or 0.0)
            if value > peaked_ms[src]:
                peaked_ms[src] = value
    return {dst: _seconds(peaked_ms[src]) for src, dst in mapping}


class SyncBusyError(RuntimeError):
    """Raised when a sync is requested while another sync holds the run lock."""


def sync_all_projects(db: Session, study_id: str) -> dict[str, Any]:
    """Sync all Kobo forms for a study.

    Non-blocking on the run lock: a second concurrent UI/API sync gets
    :class:`SyncBusyError` instead of hanging until the first finishes.
    """
    if not _SYNC_RUN_LOCK.acquire(blocking=False):
        raise SyncBusyError("A Kobo sync is already in progress for this process")
    try:
        return _sync_all_projects_unlocked(db, study_id)
    finally:
        _SYNC_RUN_LOCK.release()


def try_sync_all_projects(db: Session, study_id: str) -> dict[str, Any] | None:
    """Non-blocking sync for the periodic auto-sync tick. Returns None if busy."""
    if not _SYNC_RUN_LOCK.acquire(blocking=False):
        logger.info("auto_sync_skipped", reason="sync_busy", study_id=study_id)
        return None
    try:
        return _sync_all_projects_unlocked(db, study_id)
    finally:
        _SYNC_RUN_LOCK.release()


def _sync_all_projects_unlocked(db: Session, study_id: str) -> dict[str, Any]:
    study = db.get(Study, study_id)
    if not study:
        raise LookupError("Study not found")
    client = _configured_client(db, study_id)
    study_timezone = study.timezone
    workers = _sync_concurrency()

    t0 = time.perf_counter()
    logger.info(
        "sync_all_listing_forms",
        study_id=study_id,
        workers=workers,
    )
    t_list = time.perf_counter()
    assets = [
        asset
        for asset in client.list_assets()
        if not asset.get("asset_type") or asset.get("asset_type") == "survey"
    ]
    list_assets_ms = (time.perf_counter() - t_list) * 1000.0

    logger.info(
        "sync_all_started",
        study_id=study_id,
        forms=len(assets),
        workers=workers,
    )

    errors: list[str] = []
    projects_synced = 0
    submissions_fetched = 0
    new_submissions = 0
    deleted_submissions = 0
    touched_by_project: dict[str, set[str]] = {}
    form_phase_lists: list[dict[str, float]] = []

    # Preserve asset list order when collecting errors/results.
    indexed = list(enumerate(assets))

    def _run(item: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        index, asset = item
        outcome = _sync_one_asset_worker(
            client=client,
            asset=asset,
            study_id=study_id,
            study_timezone=study_timezone,
        )
        return index, outcome

    t_forms = time.perf_counter()
    if not assets:
        outcomes: list[dict[str, Any]] = []
    elif workers == 1:
        outcomes = [_run(item)[1] for item in indexed]
    else:
        by_index: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_run, item) for item in indexed]
            for future in as_completed(futures):
                index, outcome = future.result()
                by_index[index] = outcome
        outcomes = [by_index[i] for i in range(len(assets))]
    forms_wall_ms = (time.perf_counter() - t_forms) * 1000.0

    for outcome in outcomes:
        if not outcome.get("ok"):
            errors.append(f"{outcome.get('asset_name')}: {outcome.get('error')}")
            continue
        result = outcome["result"]
        projects_synced += 1
        submissions_fetched += result["submissions_fetched"]
        new_submissions += result["new_submissions"]
        deleted_submissions += result["deleted_submissions"]
        touched = result.get("touched_submission_ids") or set()
        if touched:
            touched_by_project[result["project_id"]] = set(touched)
        phases = result.get("phase_ms")
        if isinstance(phases, dict):
            form_phase_lists.append(phases)

    # Request session may be stale after concurrent commits on other connections.
    with _SYNC_DB_LOCK:
        db.expire_all()

        t_maps = time.perf_counter()
        try:
            from app.services import studies as studies_service

            studies_service.apply_all_study_form_maps(db)
        except Exception:
            logger.exception(
                "study_tool_assignment_failed",
                study_id=study_id,
                phase="after_sync_all",
            )
        form_maps_ms = (time.perf_counter() - t_maps) * 1000.0

        t_canon = time.perf_counter()
        _canonicalize_study_enumerators(db, study_id)
        canonicalize_ms = (time.perf_counter() - t_canon) * 1000.0

        t_dqa = time.perf_counter()
        for project_id, touched_ids in touched_by_project.items():
            _run_dqa_for_touched(db, project_id, touched_ids)
        dqa_post_ms = (time.perf_counter() - t_dqa) * 1000.0

    total_ms = (time.perf_counter() - t0) * 1000.0
    logger.info(
        "sync_all_complete",
        message="Summary of sync duration",
        study_id=study_id,
        forms=len(assets),
        forms_ok=projects_synced,
        forms_failed=len(errors),
        workers=workers,
        duration_s={
            "list_forms": _seconds(list_assets_ms),
            "sync_forms": _seconds(forms_wall_ms),
            "assign_tools": _seconds(form_maps_ms),
            "canonicalize_enumerators": _seconds(canonicalize_ms),
            "run_dqa": _seconds(dqa_post_ms),
            "total": _seconds(total_ms),
        },
        slowest_form_s=_slowest_form_s(form_phase_lists),
    )

    return {
        "success": len(errors) == 0,
        "projects_synced": projects_synced,
        "submissions_fetched": submissions_fetched,
        "new_submissions": new_submissions,
        "deleted_submissions": deleted_submissions,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }


def sync_project(db: Session, project_id: str) -> dict[str, Any]:
    if not _SYNC_RUN_LOCK.acquire(blocking=False):
        raise SyncBusyError("A Kobo sync is already in progress for this process")
    try:
        return _sync_project_unlocked(db, project_id)
    finally:
        _SYNC_RUN_LOCK.release()


def _sync_project_unlocked(db: Session, project_id: str) -> dict[str, Any]:
    project = db.scalars(
        select(Project).options(joinedload(Project.study)).where(Project.id == project_id)
    ).first()
    if not project:
        raise LookupError("Project not found")
    if not project.study_id:
        raise ValueError(
            "Project is not assigned to a study. Assign it to a study before syncing."
        )
    study = project.study or db.get(Study, project.study_id)
    client = _configured_client(db, project.study_id)
    asset = client.get_asset(project.uid)
    result = _sync_asset(
        db,
        client,
        asset,
        study_id=project.study_id,
        study_timezone=study.timezone if study else None,
        run_post_hooks=True,
        canonicalize_enumerators=True,
    )
    if study:
        _canonicalize_study_enumerators(db, study.id)
    return {
        "success": True,
        "projects_synced": 1,
        "submissions_fetched": result["submissions_fetched"],
        "new_submissions": result["new_submissions"],
        "deleted_submissions": result["deleted_submissions"],
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
    }
