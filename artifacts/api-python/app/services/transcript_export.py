"""Build transcript export documents (DOCX/PDF) with summary header and diarized body."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AudioRecording, Study
from app.integrations.transcription.base import TranscriptSegment
from app.services.audio_storage import reports_dir
from app.services.transcript_storage import load_speaker_labels, load_transcript
from app.services.transcript_segments import (
    DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
    TranscriptSegmentLayout,
    apply_segment_layout,
)

LEGACY_TRANSCRIPT_DOCX_FILENAME = "transcript.docx"
LEGACY_TRANSCRIPT_PDF_FILENAME = "transcript-v2.pdf"


@dataclass(frozen=True)
class TranscriptExportContext:
    recording_name: str
    study_name: str
    description: str
    original_filename: str
    duration_seconds: float | None
    transcribed_at: str | None
    transcription_provider: str | None
    transcription_model: str | None
    transcription_language: str | None
    transcription_cost_amount: float | None
    transcription_cost_currency: str | None
    total_utterances: int
    word_count: int
    speaker_stats: str
    segments: list[dict[str, Any]]
    exported_at: str


def transcript_docx_path(
    storage_folder: str,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> Path:
    return reports_dir(storage_folder) / f"transcript-{segment_layout}.docx"


def transcript_pdf_path(
    storage_folder: str,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> Path:
    return reports_dir(storage_folder) / f"transcript-{segment_layout}.pdf"


def clear_transcript_exports(storage_folder: str) -> None:
    reports = reports_dir(storage_folder)
    if not reports.is_dir():
        return
    for path in reports.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if name in {LEGACY_TRANSCRIPT_DOCX_FILENAME, LEGACY_TRANSCRIPT_PDF_FILENAME}:
            path.unlink()
            continue
        if name.startswith("transcript-") and name.endswith((".docx", ".pdf")):
            path.unlink()


def format_duration_minutes(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return "—"
    return f"{seconds / 60.0:.2f} minutes"


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _display_date(value: datetime | str | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%b %Y")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%b %Y")
    except ValueError:
        return str(value)


def _speaker_label(speaker_id: str | None, labels: dict[str, str]) -> str:
    if speaker_id is None or speaker_id == "":
        return "Unknown"
    custom = labels.get(speaker_id, "").strip()
    if custom:
        return custom
    numeric = float(speaker_id) if speaker_id.replace(".", "", 1).isdigit() else None
    if numeric is not None:
        return f"Speaker {int(numeric) + 1}"
    return f"Speaker {speaker_id}"


def _speaker_stats(segments: list[dict[str, Any]], labels: dict[str, str]) -> str:
    counts: dict[str, int] = {}
    for segment in segments:
        speaker_id = str(segment.get("speakerId") or "unknown")
        counts[speaker_id] = counts.get(speaker_id, 0) + 1

    if not counts:
        return "—"

    parts = [
        f"{count} {_speaker_label(speaker_id, labels)} utts"
        for speaker_id, count in sorted(
            counts.items(),
            key=lambda item: (
                float(item[0]) if item[0].replace(".", "", 1).isdigit() else item[0]
            ),
        )
    ]
    return " + ".join(parts)


def _word_count(full_text: str, segments: list[dict[str, Any]]) -> int:
    text = full_text.strip()
    if not text and segments:
        text = " ".join(str(segment.get("text") or "") for segment in segments)
    if not text:
        return 0
    return len(text.split())


def build_export_context(
    db: Session,
    recording: AudioRecording,
    *,
    cost_amount: float | None = None,
    cost_currency: str | None = None,
    model: str | None = None,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> TranscriptExportContext:
    transcript = load_transcript(recording.storage_folder)
    if not transcript:
        raise ValueError("Transcript not found")

    segments = [
        segment
        for segment in (transcript.get("segments") or [])
        if isinstance(segment, dict)
    ]
    raw_segments = [
        TranscriptSegment(
            speaker_id=str(item.get("speakerId")) if item.get("speakerId") is not None else None,
            start_seconds=float(item.get("startSeconds") or 0.0),
            end_seconds=float(item.get("endSeconds") or 0.0),
            text=str(item.get("text") or ""),
        )
        for item in segments
    ]
    resolved_segments = apply_segment_layout(raw_segments, segment_layout)
    segment_dicts = [
        {
            "speakerId": segment.speaker_id,
            "startSeconds": segment.start_seconds,
            "endSeconds": segment.end_seconds,
            "text": segment.text,
        }
        for segment in resolved_segments
    ]
    labels = load_speaker_labels(recording.storage_folder)
    study = db.get(Study, recording.study_id)
    study_name = study.name if study else recording.study_id

    return TranscriptExportContext(
        recording_name=recording.name,
        study_name=study_name,
        description=recording.description or "",
        original_filename=recording.original_filename or "—",
        duration_seconds=recording.duration_seconds,
        transcribed_at=_display_date(recording.transcribed_at),
        transcription_provider=recording.transcription_provider,
        transcription_model=model,
        transcription_language=transcript.get("languageCode") or recording.transcription_language,
        transcription_cost_amount=cost_amount,
        transcription_cost_currency=cost_currency,
        total_utterances=len(segment_dicts),
        word_count=_word_count(str(transcript.get("fullText") or ""), segment_dicts),
        speaker_stats=_speaker_stats(segment_dicts, labels),
        segments=[
            {
                "speaker": _speaker_label(segment.get("speakerId"), labels),
                "start_seconds": float(segment.get("startSeconds") or 0.0),
                "end_seconds": float(segment.get("endSeconds") or 0.0),
                "text": str(segment.get("text") or ""),
            }
            for segment in segment_dicts
        ],
        exported_at=datetime.now(timezone.utc).strftime("%b %Y"),
    )


def get_or_build_docx(
    db: Session,
    recording: AudioRecording,
    *,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> bytes:
    path = transcript_docx_path(recording.storage_folder, segment_layout)
    if path.is_file():
        return path.read_bytes()

    from app.rendering.transcript_docx import render_transcript_docx
    from app.services.audio import _latest_transcription_usage

    amount, currency, model = _latest_transcription_usage(db, recording.id)
    context = build_export_context(
        db,
        recording,
        cost_amount=amount,
        cost_currency=currency,
        model=model,
        segment_layout=segment_layout,
    )
    docx_bytes = render_transcript_docx(context)
    path.write_bytes(docx_bytes)
    return docx_bytes


def get_or_build_pdf(
    db: Session,
    recording: AudioRecording,
    *,
    segment_layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> bytes:
    path = transcript_pdf_path(recording.storage_folder, segment_layout)
    if path.is_file():
        return path.read_bytes()

    from app.rendering.transcript_pdf import render_transcript_pdf
    from app.services.audio import _latest_transcription_usage

    amount, currency, model = _latest_transcription_usage(db, recording.id)
    context = build_export_context(
        db,
        recording,
        cost_amount=amount,
        cost_currency=currency,
        model=model,
        segment_layout=segment_layout,
    )
    pdf_bytes = render_transcript_pdf(context)
    path.write_bytes(pdf_bytes)
    return pdf_bytes
