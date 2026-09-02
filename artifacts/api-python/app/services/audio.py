"""Audio recording CRUD and helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AudioRecording, Study, UsageEvent
from app.integrations.transcription.base import TranscriptSegment
from app.schemas.audio import (
    AudioRecordingOut,
    AudioRecordingSummary,
    TranscriptOut,
    TranscriptSegmentOut,
)
from app.services import settings as settings_service
from app.services.audio_duration import probe_audio_duration_seconds
from app.services.audio_storage import (
    audio_path_for,
    build_storage_folder,
    delete_recording_assets,
    guess_extension,
    locate_recording_source,
    normalize_recording_name,
)
from app.services.transcript_export import clear_transcript_exports
from app.services.transcript_segments import (
    DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
    TranscriptSegmentLayout,
    apply_segment_layout,
)
from app.services.transcript_storage import (
    load_speaker_labels,
    load_transcript,
    save_speaker_labels,
)
from app.services.transcription_cost import estimate_amount


class DuplicateRecordingNameError(ValueError):
    """Raised when a recording name already exists within a study."""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def file_url_for(recording_id: str) -> str:
    return f"/api/audio/{recording_id}/file"


def source_path_for(row: AudioRecording) -> Path:
    return locate_recording_source(
        storage_folder=row.storage_folder,
        storage_path=row.storage_path,
        original_filename=row.original_filename,
        content_type=row.content_type,
    )


def _latest_transcription_usage(
    db: Session, recording_id: str
) -> tuple[float | None, str | None, str | None]:
    row = db.scalar(
        select(UsageEvent)
        .where(
            UsageEvent.resource_type == "audio_recording",
            UsageEvent.resource_id == recording_id,
            UsageEvent.category == "transcription",
        )
        .order_by(UsageEvent.occurred_at.desc())
        .limit(1)
    )
    if not row:
        return None, None, None
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    model = metadata.get("model")
    return row.amount, row.currency, str(model) if model else None


def _map_transcript(
    data: dict | None,
    *,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> TranscriptOut | None:
    if not data:
        return None
    raw_segments = [
        TranscriptSegment(
            speaker_id=str(item.get("speakerId")) if item.get("speakerId") is not None else None,
            start_seconds=float(item.get("startSeconds") or 0.0),
            end_seconds=float(item.get("endSeconds") or 0.0),
            text=str(item.get("text") or ""),
        )
        for item in (data.get("segments") or [])
        if isinstance(item, dict)
    ]
    segments = [
        TranscriptSegmentOut(
            speaker_id=segment.speaker_id,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            text=segment.text,
        )
        for segment in apply_segment_layout(raw_segments, segment_layout)
    ]
    return TranscriptOut(
        language_code=data.get("languageCode"),
        full_text=str(data.get("fullText") or ""),
        segments=segments,
        segment_layout=segment_layout,
    )


def _map_transcript_for_recording(
    storage_folder: str,
    data: dict | None,
    *,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> TranscriptOut | None:
    if not data:
        return None
    transcript = _map_transcript(data, segment_layout=segment_layout)
    if transcript is None:
        return None
    transcript.speaker_labels = load_speaker_labels(storage_folder)
    return transcript


def _transcription_cost_estimate(
    db: Session, row: AudioRecording
) -> tuple[float | None, str | None, float | None, float | None]:
    settings = settings_service.get_or_create_settings(db)
    duration = row.duration_seconds
    if not duration or duration <= 0:
        try:
            duration = probe_audio_duration_seconds(str(source_path_for(row)))
        except FileNotFoundError:
            duration = None

    rate = float(settings.transcription_rate_per_minute or 0.0)
    currency = settings.transcription_currency or "INR"
    if not duration or duration <= 0:
        return None, currency, None, rate if rate > 0 else None

    amount, currency = estimate_amount(
        settings,
        duration_seconds=float(duration),
        provider_amount=None,
    )
    return (amount if amount > 0 else None), currency, float(duration), rate if rate > 0 else None


def _assert_unique_name(
    db: Session,
    *,
    study_id: str,
    name: str,
    exclude_recording_id: str | None = None,
) -> None:
    normalized = normalize_recording_name(name)
    if not normalized:
        raise ValueError("name is required")
    query = select(AudioRecording.id).where(
        AudioRecording.study_id == study_id,
        AudioRecording.name_normalized == normalized,
    )
    if exclude_recording_id:
        query = query.where(AudioRecording.id != exclude_recording_id)
    if db.scalar(query):
        raise DuplicateRecordingNameError(
            f"A recording named “{name.strip()}” already exists in this study"
        )


def to_summary(db: Session, row: AudioRecording) -> AudioRecordingSummary:
    amount, currency, _model = _latest_transcription_usage(db, row.id)
    est_amount, est_currency, est_duration, rate = _transcription_cost_estimate(db, row)
    return AudioRecordingSummary(
        id=row.id,
        study_id=row.study_id,
        name=row.name,
        description=row.description or "",
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_seconds=row.duration_seconds,
        transcription_status=row.transcription_status,
        transcription_provider=row.transcription_provider,
        transcription_language=row.transcription_language,
        transcription_error=row.transcription_error,
        transcribed_at=_iso(row.transcribed_at),
        file_url=file_url_for(row.id),
        transcription_cost_amount=amount,
        transcription_cost_currency=currency,
        estimated_transcription_cost_amount=est_amount,
        estimated_transcription_cost_currency=est_currency,
        estimated_transcription_duration_seconds=est_duration,
        transcription_rate_per_minute=rate,
        created_at=_iso(row.created_at) or "",
        updated_at=_iso(row.updated_at) or "",
    )


def to_out(
    db: Session,
    row: AudioRecording,
    *,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> AudioRecordingOut:
    amount, currency, model = _latest_transcription_usage(db, row.id)
    est_amount, est_currency, est_duration, rate = _transcription_cost_estimate(db, row)
    return AudioRecordingOut(
        id=row.id,
        study_id=row.study_id,
        name=row.name,
        description=row.description or "",
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        duration_seconds=row.duration_seconds,
        transcription_status=row.transcription_status,
        transcription_provider=row.transcription_provider,
        transcription_language=row.transcription_language,
        transcription_error=row.transcription_error,
        transcript=_map_transcript_for_recording(
            row.storage_folder,
            load_transcript(row.storage_folder),
            segment_layout=segment_layout,
        ),
        transcribed_at=_iso(row.transcribed_at),
        file_url=file_url_for(row.id),
        transcription_cost_amount=amount,
        transcription_cost_currency=currency,
        transcription_model=model,
        estimated_transcription_cost_amount=est_amount,
        estimated_transcription_cost_currency=est_currency,
        estimated_transcription_duration_seconds=est_duration,
        transcription_rate_per_minute=rate,
        created_at=_iso(row.created_at) or "",
        updated_at=_iso(row.updated_at) or "",
    )


def update_speaker_labels(
    db: Session,
    row: AudioRecording,
    labels: dict[str, str],
) -> AudioRecording:
    save_speaker_labels(row.storage_folder, labels)
    clear_transcript_exports(row.storage_folder)
    db.commit()
    db.refresh(row)
    return row


def list_recordings(db: Session, study_id: str) -> list[AudioRecordingSummary]:
    rows = db.scalars(
        select(AudioRecording)
        .where(AudioRecording.study_id == study_id)
        .order_by(AudioRecording.created_at.desc())
    ).all()
    return [to_summary(db, row) for row in rows]


def get_recording(db: Session, recording_id: str) -> AudioRecording | None:
    return db.get(AudioRecording, recording_id)


def create_recording(
    db: Session,
    *,
    study_id: str,
    name: str,
    description: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> AudioRecording:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ValueError("name is required")

    study = db.get(Study, study_id)
    if not study:
        raise ValueError("Study not found")

    _assert_unique_name(db, study_id=study_id, name=cleaned_name)

    recording_id = str(uuid.uuid4())
    storage_folder = build_storage_folder(
        study_name=study.name,
        study_id=study.id,
        recording_name=cleaned_name,
    )
    extension = guess_extension(content_type, filename)
    path = audio_path_for(storage_folder, extension)
    path.write_bytes(data)

    duration_seconds = probe_audio_duration_seconds(path)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = AudioRecording(
        id=recording_id,
        study_id=study_id,
        name=cleaned_name,
        name_normalized=normalize_recording_name(cleaned_name),
        description=description.strip(),
        original_filename=filename,
        content_type=content_type or "application/octet-stream",
        storage_folder=storage_folder,
        storage_path=str(path),
        size_bytes=len(data),
        duration_seconds=duration_seconds,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_recording(
    db: Session,
    row: AudioRecording,
    *,
    name: str | None = None,
    description: str | None = None,
) -> AudioRecording:
    if name is not None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("name is required")
        _assert_unique_name(
            db,
            study_id=row.study_id,
            name=cleaned_name,
            exclude_recording_id=row.id,
        )
        row.name = cleaned_name
        row.name_normalized = normalize_recording_name(cleaned_name)
    if description is not None:
        row.description = description.strip()
    db.commit()
    db.refresh(row)
    return row


def delete_recording(db: Session, row: AudioRecording) -> None:
    storage_path = row.storage_path
    storage_folder = row.storage_folder
    db.delete(row)
    db.commit()
    delete_recording_assets(storage_folder, storage_path)
