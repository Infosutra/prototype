"""Tests for transcript DOCX/PDF export."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AudioRecording, Study
from app.services.audio_storage import build_storage_folder, normalize_recording_name
from app.services.transcript_export import (
    build_export_context,
    clear_transcript_exports,
    get_or_build_docx,
    get_or_build_pdf,
    transcript_docx_path,
    transcript_pdf_path,
)
from app.services.transcript_storage import save_speaker_labels, save_transcripts


@pytest.fixture()
def db() -> Session:
    from app.db.base import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_transcript(storage_folder: str) -> None:
    save_transcripts(
        storage_folder,
        normalized={
            "languageCode": "hi-IN",
            "fullText": "नमस्ते दुनिया",
            "segments": [
                {
                    "speakerId": "1",
                    "startSeconds": 9.01,
                    "endSeconds": 12.5,
                    "text": "नमस्ते",
                },
                {
                    "speakerId": "2",
                    "startSeconds": 13.0,
                    "endSeconds": 15.2,
                    "text": "दुनिया",
                },
            ],
        },
        raw={"text": "raw"},
    )
    save_speaker_labels(storage_folder, {"1": "Kiran", "2": "Interviewer"})


def test_build_export_context_and_render_exports(db, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)

    study_row = Study(
        id="study-export",
        name="Sightsavers 2030",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study_row)
    db.commit()

    storage_folder = build_storage_folder(
        study_name=study_row.name,
        study_id=study_row.id,
        recording_name="Kiran Gautam",
    )
    _seed_transcript(storage_folder)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recording = AudioRecording(
        id="rec-export",
        study_id=study_row.id,
        name="Kiran Gautam",
        name_normalized=normalize_recording_name("Kiran Gautam"),
        description="IDI participant",
        original_filename="kiran.mp3",
        content_type="audio/mpeg",
        storage_folder=storage_folder,
        storage_path=str(tmp_path / storage_folder / "source.mp3"),
        size_bytes=100,
        duration_seconds=2495.4,
        transcription_status="succeeded",
        transcription_provider="sarvam",
        transcription_language="hi-IN",
        transcribed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(recording)
    db.commit()

    context = build_export_context(db, recording, model="saaras-v3")
    assert context.total_utterances == 2
    assert "Kiran" in context.speaker_stats
    assert context.segments[0]["speaker"] == "Kiran"

    docx_bytes = get_or_build_docx(db, recording)
    pdf_bytes = get_or_build_pdf(db, recording)
    assert docx_bytes.startswith(b"PK")
    assert pdf_bytes.startswith(b"%PDF")
    assert transcript_docx_path(storage_folder).is_file()
    assert transcript_pdf_path(storage_folder).is_file()
    assert transcript_pdf_path(storage_folder).name == "transcript-linear.pdf"

    pdf_text = pdf_bytes.decode("latin-1", errors="ignore")
    assert "Kiran" in pdf_text

    provider_context = build_export_context(db, recording, model="saaras-v3", segment_layout="provider")
    assert provider_context.total_utterances == 2

    clear_transcript_exports(storage_folder)
    assert not transcript_docx_path(storage_folder).is_file()
    assert not transcript_pdf_path(storage_folder).is_file()
