"""Transcription job orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppSettings, AudioRecording, UsageEvent
from app.db.session import SessionLocal
from app.integrations.transcription.base import JobRef, transcript_to_dict
from app.integrations.transcription.factory import get_transcription_provider
from app.integrations.transcription.whisper import WhisperProvider
from app.services import settings as settings_service
from app.services.audio_storage import locate_recording_source
from app.services.transcript_export import clear_transcript_exports
from app.services.transcript_storage import clear_transcripts, save_transcripts
from app.services.transcription_cost import estimate_amount

logger = structlog.stdlib.get_logger(__name__)


def _log_transcription_failure(
    *,
    recording_id: str,
    reason: str,
    provider: str | None = None,
    job_id: str | None = None,
    error: str | None = None,
    warning: bool = False,
) -> None:
    log = logger.warning if warning else logger.error
    log(
        "transcription_failed",
        recording_id=recording_id,
        provider=provider,
        job_id=job_id,
        reason=reason,
        error=error[:500] if error else None,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _estimate_amount(
    settings_row: AppSettings,
    *,
    duration_seconds: float,
    provider_amount: float | None,
) -> tuple[float, str]:
    return estimate_amount(
        settings_row,
        duration_seconds=duration_seconds,
        provider_amount=provider_amount,
    )


def record_usage_event(
    db: Session,
    *,
    settings_row: AppSettings,
    recording: AudioRecording,
    provider: str,
    operation: str,
    quantity: float,
    unit: str,
    amount: float,
    currency: str,
    metadata: dict | None = None,
) -> UsageEvent:
    event = UsageEvent(
        id=str(uuid.uuid4()),
        occurred_at=_utcnow(),
        category="transcription",
        provider=provider,
        operation=operation,
        quantity=quantity,
        unit=unit,
        amount=amount,
        currency=currency,
        study_id=recording.study_id,
        resource_type="audio_recording",
        resource_id=recording.id,
        metadata_json=metadata or {},
    )
    db.add(event)
    return event


def process_recording_transcription(recording_id: str) -> None:
    db = SessionLocal()
    try:
        recording = db.get(AudioRecording, recording_id)
        if not recording:
            return
        if recording.transcription_status not in {"queued", "running"}:
            return

        settings_row = settings_service.get_or_create_settings(db)
        if not settings_row.transcription_enabled:
            _log_transcription_failure(
                recording_id=recording_id,
                reason="disabled_in_settings",
                warning=True,
            )
            recording.transcription_status = "failed"
            recording.transcription_error = "Transcription is disabled in settings"
            db.commit()
            return

        provider = get_transcription_provider(settings_row)
        recording.transcription_provider = provider.provider_name
        recording.transcription_status = "running"
        db.commit()

        if isinstance(provider, WhisperProvider):
            _run_whisper_sync(db, settings_row, recording, provider)
            return

        if recording.transcription_job_ref:
            job_ref = JobRef(
                provider=provider.provider_name,
                job_id=recording.transcription_job_ref,
            )
            poll = provider.poll(job_ref)
        else:
            language = recording.transcription_language
            source_path = str(
                locate_recording_source(
                    storage_folder=recording.storage_folder,
                    storage_path=recording.storage_path,
                    original_filename=recording.original_filename,
                    content_type=recording.content_type,
                )
            )
            job_ref = provider.submit(source_path, language_code=language)
            recording.transcription_job_ref = job_ref.job_id
            db.commit()
            poll = provider.poll(job_ref)

        if poll.status == "pending":
            return

        if poll.status == "failed":
            error_message = poll.error or "Transcription failed"
            _log_transcription_failure(
                recording_id=recording_id,
                reason="provider_reported_failure",
                provider=provider.provider_name,
                job_id=recording.transcription_job_ref,
                error=error_message,
            )
            recording.transcription_status = "failed"
            recording.transcription_error = error_message
            db.commit()
            return

        raw = poll.raw or {}
        transcript, usage_hint = provider.normalize(raw)
        save_transcripts(
            recording.storage_folder,
            normalized=transcript_to_dict(transcript),
            raw=raw,
        )
        recording.transcription_language = transcript.language_code
        recording.transcription_status = "succeeded"
        recording.transcription_error = None
        recording.transcribed_at = _utcnow()
        if usage_hint and usage_hint.quantity > 0:
            recording.duration_seconds = usage_hint.quantity

        duration = float(recording.duration_seconds or usage_hint.quantity if usage_hint else 0.0)
        amount, currency = _estimate_amount(
            settings_row,
            duration_seconds=duration,
            provider_amount=usage_hint.amount if usage_hint else None,
        )
        record_usage_event(
            db,
            settings_row=settings_row,
            recording=recording,
            provider=provider.provider_name,
            operation="stt.batch",
            quantity=duration,
            unit=usage_hint.unit if usage_hint else "audio_seconds",
            amount=amount,
            currency=currency,
            metadata={
                "model": settings_row.transcription_model,
                "jobId": recording.transcription_job_ref,
            },
        )
        db.commit()
    except Exception as exc:
        provider_name: str | None = None
        job_id: str | None = None
        try:
            failed_recording = db.get(AudioRecording, recording_id)
            if failed_recording:
                provider_name = failed_recording.transcription_provider
                job_id = failed_recording.transcription_job_ref
        except Exception:
            pass
        logger.exception(
            "transcription_failed",
            recording_id=recording_id,
            provider=provider_name or "-",
            job_id=job_id or "-",
            reason="unexpected_exception",
        )
        try:
            recording = db.get(AudioRecording, recording_id)
            if recording:
                recording.transcription_status = "failed"
                recording.transcription_error = str(exc)[:1000]
                db.commit()
        except Exception:
            logger.exception(
                "transcription_error_persist_failed",
                recording_id=recording_id,
            )
    finally:
        db.close()


def _run_whisper_sync(
    db: Session,
    settings_row: AppSettings,
    recording: AudioRecording,
    provider: WhisperProvider,
) -> None:
    source_path = str(
        locate_recording_source(
            storage_folder=recording.storage_folder,
            storage_path=recording.storage_path,
            original_filename=recording.original_filename,
            content_type=recording.content_type,
        )
    )
    raw, transcript, usage_hint = provider.transcribe_sync(
        source_path,
        language_code=recording.transcription_language,
    )
    save_transcripts(
        recording.storage_folder,
        normalized=transcript_to_dict(transcript),
        raw=raw,
    )
    recording.transcription_language = transcript.language_code
    recording.transcription_status = "succeeded"
    recording.transcription_error = None
    recording.transcribed_at = _utcnow()
    if usage_hint and usage_hint.quantity > 0:
        recording.duration_seconds = usage_hint.quantity

    duration = float(recording.duration_seconds or 0.0)
    amount, currency = _estimate_amount(
        settings_row,
        duration_seconds=duration,
        provider_amount=usage_hint.amount if usage_hint else None,
    )
    record_usage_event(
        db,
        settings_row=settings_row,
        recording=recording,
        provider=provider.provider_name,
        operation="stt.sync",
        quantity=duration,
        unit=usage_hint.unit if usage_hint else "audio_seconds",
        amount=amount,
        currency=currency,
        metadata={"model": settings_row.transcription_model},
    )
    db.commit()


def queue_transcription(
    db: Session,
    recording: AudioRecording,
    *,
    language_code: str | None = None,
) -> AudioRecording:
    settings_row = settings_service.get_or_create_settings(db)
    if not settings_row.transcription_enabled:
        raise ValueError("Transcription is disabled in settings")
    api_key = settings_service.get_transcription_api_key(settings_row)
    if not api_key:
        raise ValueError("Transcription API key is not configured")

    recording.transcription_status = "queued"
    recording.transcription_language = language_code
    recording.transcription_error = None
    recording.transcription_job_ref = None
    recording.transcribed_at = None
    clear_transcripts(recording.storage_folder)
    clear_transcript_exports(recording.storage_folder)
    db.commit()
    db.refresh(recording)
    return recording


def drain_pending_transcriptions() -> None:
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(AudioRecording.id).where(
                AudioRecording.transcription_status.in_(["queued", "running"])
            )
        ).all()
    finally:
        db.close()

    for recording_id in rows:
        process_recording_transcription(recording_id)


def job_ref_from_recording(recording: AudioRecording) -> JobRef | None:
    if not recording.transcription_job_ref:
        return None
    return JobRef(
        provider=recording.transcription_provider or "sarvam",
        job_id=recording.transcription_job_ref,
    )
