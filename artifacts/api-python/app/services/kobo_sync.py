from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import Project, Study, Submission
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

logger = logging.getLogger(__name__)

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
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


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


def refresh_submission_enumerators(
    db: Session,
    *,
    project_ids: list[str],
    projects_by_id: dict[str, Project] | None = None,
) -> int:
    """Re-extract and canonicalize enumerator names for submissions in scope."""
    if not project_ids:
        return 0
    projects_by_id = projects_by_id or {
        p.id: p
        for p in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    scope_rows = list(
        db.scalars(select(Submission).where(Submission.project_id.in_(project_ids))).all()
    )
    updated = 0
    for row in scope_rows:
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

    name_counts: dict[str, int] = {}
    for row in scope_rows:
        name = (row.enumerator or "").strip()
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1
    canonical = build_enumerator_canonical_map(
        list(name_counts.keys()), counts=name_counts
    )
    for row in scope_rows:
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


def _sync_asset(
    db: Session,
    client: KoboClient,
    asset_summary: dict[str, Any],
    *,
    study_id: str | None = None,
) -> dict[str, int]:
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

    asset = client.get_asset(uid)
    versions = client.list_versions(uid)
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

    status = get_asset_status(asset)
    # Watermark must be the latest *submission* time, not wall-clock sync time.
    # Using sync-time caused later incremental queries to skip submissions that
    # arrived after the previous fetch but before the sync finished.
    watermark_dt = _naive_utc(previous.last_submission_at) if previous else None
    watermark = watermark_dt.isoformat() if watermark_dt else None
    if watermark and not watermark.endswith("Z") and "+" not in watermark:
        watermark = f"{watermark}Z"
    submissions = [] if status == "draft" else client.list_submissions(uid, modified_after=watermark)

    existing_ids = {
        row[0]
        for row in db.execute(
            select(Submission.kobo_id).where(Submission.project_id == uid)
        ).all()
    }

    new_submissions = 0
    deleted_submissions = 0
    latest_submission_at = _naive_utc(previous.last_submission_at) if previous else None
    form_definition = project.form_definition if isinstance(project.form_definition, dict) else None

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

        row = db.get(Submission, f"{uid}:{kobo_id}")
        if row is None:
            row = Submission(id=f"{uid}:{kobo_id}", kobo_id=kobo_id, project_id=uid)
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

    db.flush()

    # Incremental upsert cannot observe deletes. After a successful full remote
    # ID inventory, hard-delete local rows that Kobo no longer has.
    if status != "draft":
        remote_ids = client.list_submission_ids(uid)
        deleted_submissions = _prune_missing_submissions(db, uid, remote_ids)
        if deleted_submissions:
            logger.info(
                "Pruned %s local submission(s) missing from Kobo for project %s",
                deleted_submissions,
                uid,
            )
            db.flush()

    # Watermarked sync only rewrites newly fetched payloads. Re-derive enumerator
    # from stored JSON for every local row so extractor fixes apply without a
    # full historical re-download from Kobo.
    scope_ids = [uid]
    if project.study_id:
        scope_ids = list(
            db.scalars(
                select(Project.id).where(Project.study_id == project.study_id)
            ).all()
        ) or [uid]
    refreshed_enumerators = refresh_submission_enumerators(
        db,
        project_ids=scope_ids,
        projects_by_id={
            p.id: p
            for p in db.scalars(select(Project).where(Project.id.in_(scope_ids))).all()
        },
    )
    if refreshed_enumerators:
        logger.info(
            "Refreshed enumerator on %s submission(s) for project %s",
            refreshed_enumerators,
            uid,
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

    try:
        from app.services import studies as studies_service

        studies_service.apply_all_study_form_maps(db)
    except Exception:
        logger.exception("Study tool assignment failed after sync of %s", uid)

    try:
        from app.services import dqa_engine

        dqa_engine.evaluate_project(db, uid)
    except Exception:
        logger.exception("DQA evaluation failed for project %s", uid)

    return {
        "submissions_fetched": len(submissions),
        "new_submissions": new_submissions,
        "deleted_submissions": deleted_submissions,
    }


def sync_all_projects(db: Session, study_id: str) -> dict[str, Any]:
    study = db.get(Study, study_id)
    if not study:
        raise LookupError("Study not found")
    client = _configured_client(db, study_id)
    assets = [
        asset
        for asset in client.list_assets()
        if not asset.get("asset_type") or asset.get("asset_type") == "survey"
    ]
    errors: list[str] = []
    projects_synced = 0
    submissions_fetched = 0
    new_submissions = 0
    deleted_submissions = 0

    for asset in assets:
        try:
            result = _sync_asset(db, client, asset, study_id=study_id)
            projects_synced += 1
            submissions_fetched += result["submissions_fetched"]
            new_submissions += result["new_submissions"]
            deleted_submissions += result["deleted_submissions"]
        except Exception as exc:
            message = str(exc)
            errors.append(f"{get_asset_name(asset)}: {message}")
            logger.exception("Failed syncing asset %s", asset.get("uid"))
            project = db.get(Project, str(asset.get("uid")))
            if project:
                project.sync_status = "failed"
                project.sync_error = message[:1000]
                project.last_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
                project.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()

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
    project = db.scalars(
        select(Project).options(joinedload(Project.study)).where(Project.id == project_id)
    ).first()
    if not project:
        raise LookupError("Project not found")
    if not project.study_id:
        raise ValueError(
            "Project is not assigned to a study. Assign it to a study before syncing."
        )
    client = _configured_client(db, project.study_id)
    asset = client.get_asset(project.uid)
    result = _sync_asset(db, client, asset, study_id=project.study_id)
    return {
        "success": True,
        "projects_synced": 1,
        "submissions_fetched": result["submissions_fetched"],
        "new_submissions": result["new_submissions"],
        "deleted_submissions": result["deleted_submissions"],
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
    }
