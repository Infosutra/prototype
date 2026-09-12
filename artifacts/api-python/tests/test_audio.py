"""Tests for audio recordings and usage ledger."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import AppSettings, AudioRecording, Study, UsageEvent
from app.integrations.transcription.base import PollResult, Transcript, TranscriptSegment, UsageHint
from app.integrations.transcription.whisper import WhisperProvider
from app.services import audio as audio_service
from app.services.audio_storage import build_storage_folder, normalize_recording_name, transcript_path
from app.services.transcript_storage import load_transcript
from app.services.transcription_job import (
    process_recording_transcription,
    queue_transcription,
    record_usage_event,
)


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


def _seed_study(db: Session) -> Study:
    study = Study(
        id="study-audio",
        name="Audio Study",
        description=None,
        start_date=None,
        end_date=None,
        timezone="UTC",
    )
    db.add(study)
    db.commit()
    return study


def _seed_settings(db: Session, *, enabled: bool = True, rate: float = 2.5) -> AppSettings:
    row = AppSettings(
        id="singleton",
        transcription_enabled=enabled,
        transcription_provider="whisper",
        transcription_api_key_encrypted="",
        transcription_base_url="https://api.openai.com/v1",
        transcription_model="whisper-1",
        transcription_currency="INR",
        transcription_rate_per_minute=rate,
    )
    db.add(row)
    db.commit()
    return row


def test_create_list_delete_recording(db: Session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    study = _seed_study(db)
    row = audio_service.create_recording(
        db,
        study_id=study.id,
        name="Interview 1",
        description="Block debrief",
        filename="clip.mp3",
        content_type="audio/mpeg",
        data=b"fake-audio-bytes",
    )
    assert row.name == "Interview 1"
    assert row.transcription_status == "none"
    assert row.storage_folder == "audio-study/interview-1"
    assert (tmp_path / row.storage_folder / "source.mp3").is_file()
    assert (tmp_path / row.storage_folder / "reports").is_dir()

    listed = audio_service.list_recordings(db, study.id)
    assert len(listed) == 1
    assert listed[0].file_url.endswith(f"/api/audio/{row.id}/file")

    audio_service.delete_recording(db, row)
    assert audio_service.get_recording(db, row.id) is None
    assert not (tmp_path / row.storage_folder).exists()


def test_create_recording_probes_wav_duration(db: Session, tmp_path, monkeypatch):
    import wave

    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    study = _seed_study(db)
    _seed_settings(db, rate=3.0)

    wav_path = tmp_path / "clip.wav"
    with wave.open(str(wav_path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 16000)  # 2 seconds

    row = audio_service.create_recording(
        db,
        study_id=study.id,
        name="WAV clip",
        description="",
        filename="clip.wav",
        content_type="audio/wav",
        data=wav_path.read_bytes(),
    )

    assert row.duration_seconds is not None
    assert abs(row.duration_seconds - 2.0) < 0.01

    summary = audio_service.to_summary(db, row)
    assert summary.estimated_transcription_cost_amount == 3.0
    assert summary.estimated_transcription_cost_currency == "INR"
    assert summary.estimated_transcription_duration_seconds == row.duration_seconds
    assert summary.transcription_rate_per_minute == 3.0


def test_create_recording_rejects_duplicate_name(db: Session, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    study = _seed_study(db)
    audio_service.create_recording(
        db,
        study_id=study.id,
        name="Interview 1",
        description="",
        filename="clip.mp3",
        content_type="audio/mpeg",
        data=b"fake-audio-bytes",
    )
    with pytest.raises(audio_service.DuplicateRecordingNameError):
        audio_service.create_recording(
            db,
            study_id=study.id,
            name=" interview 1 ",
            description="",
            filename="clip2.mp3",
            content_type="audio/mpeg",
            data=b"more-audio",
        )


def test_record_usage_event(db: Session):
    study = _seed_study(db)
    settings = _seed_settings(db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recording = AudioRecording(
        id="rec-1",
        study_id=study.id,
        name="Test",
        name_normalized=normalize_recording_name("Test"),
        description="",
        original_filename="a.mp3",
        content_type="audio/mpeg",
        storage_folder="audio-study/test",
        storage_path="/tmp/a.mp3",
        size_bytes=100,
        created_at=now,
        updated_at=now,
    )
    db.add(recording)
    db.commit()

    record_usage_event(
        db,
        settings_row=settings,
        recording=recording,
        provider="whisper",
        operation="stt.sync",
        quantity=90.0,
        unit="audio_seconds",
        amount=5.0,
        currency="INR",
    )
    db.commit()

    events = db.scalars(select(UsageEvent)).all()
    assert len(events) == 1
    assert events[0].category == "transcription"
    assert events[0].amount == 5.0
    assert events[0].resource_id == "rec-1"


def test_queue_transcription_requires_settings(db: Session, tmp_path):
    study = _seed_study(db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    storage_folder = build_storage_folder(
        study_name=study.name,
        study_id=study.id,
        recording_name="Test",
    )
    recording = AudioRecording(
        id="rec-2",
        study_id=study.id,
        name="Test",
        name_normalized=normalize_recording_name("Test"),
        description="",
        original_filename="a.mp3",
        content_type="audio/mpeg",
        storage_folder=storage_folder,
        storage_path=str(tmp_path / storage_folder / "a.mp3"),
        size_bytes=10,
        created_at=now,
        updated_at=now,
    )
    (tmp_path / storage_folder).mkdir(parents=True)
    (tmp_path / storage_folder / "a.mp3").write_bytes(b"x")
    db.add(recording)
    db.commit()

    with pytest.raises(ValueError, match="disabled"):
        queue_transcription(db, recording)


@patch("app.services.transcription_job.get_transcription_provider")
@patch("app.services.transcription_job.settings_service.get_transcription_api_key")
@patch("app.services.transcription_job.SessionLocal")
def test_process_whisper_transcription_records_cost(
    mock_session_local,
    mock_get_key,
    mock_get_provider,
    db: Session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    study = _seed_study(db)
    settings = _seed_settings(db, rate=3.0)
    mock_get_key.return_value = "sk-test"
    mock_session_local.return_value = db

    storage_folder = build_storage_folder(
        study_name=study.name,
        study_id=study.id,
        recording_name="Whisper test",
    )
    audio_path = tmp_path / storage_folder / "source.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recording = AudioRecording(
        id="rec-3",
        study_id=study.id,
        name="Whisper test",
        name_normalized=normalize_recording_name("Whisper test"),
        description="",
        original_filename="clip.mp3",
        content_type="audio/mpeg",
        storage_folder=storage_folder,
        storage_path=str(audio_path),
        size_bytes=10,
        transcription_status="queued",
        created_at=now,
        updated_at=now,
    )
    db.add(recording)
    db.commit()

    class FakeWhisper(WhisperProvider):
        def transcribe_sync(self, _path, *, language_code=None):
            return (
                {"text": "hello"},
                Transcript(
                    language_code="en",
                    full_text="hello",
                    segments=[
                        TranscriptSegment(
                            speaker_id=None,
                            start_seconds=0.0,
                            end_seconds=65.0,
                            text="hello",
                        )
                    ],
                ),
                UsageHint(quantity=65.0, unit="audio_seconds"),
            )

    mock_get_provider.return_value = FakeWhisper(api_key="sk-test")

    process_recording_transcription("rec-3")

    updated = db.get(AudioRecording, "rec-3")
    assert updated is not None
    assert updated.transcription_status == "succeeded"
    assert updated.duration_seconds == 65.0

    transcript = load_transcript(storage_folder)
    assert transcript is not None
    assert transcript["fullText"] == "hello"
    assert transcript_path(storage_folder).is_file()

    out = audio_service.to_out(db, updated)
    assert out.transcript is not None
    assert out.transcript.full_text == "hello"

    event = db.scalar(select(UsageEvent).where(UsageEvent.resource_id == "rec-3"))
    assert event is not None
    assert event.amount == 6.0  # ceil(65/60) * 3.0


@patch("app.services.transcription_job.get_transcription_provider")
@patch("app.services.transcription_job.settings_service.get_transcription_api_key")
@patch("app.services.transcription_job.SessionLocal")
def test_process_provider_failure_is_logged(
    mock_session_local,
    mock_get_key,
    mock_get_provider,
    db: Session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    study = _seed_study(db)
    _seed_settings(db)
    mock_get_key.return_value = "sk-test"
    mock_session_local.return_value = db

    storage_folder = build_storage_folder(
        study_name=study.name,
        study_id=study.id,
        recording_name="Sarvam fail test",
    )
    audio_path = tmp_path / storage_folder / "source.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    recording = AudioRecording(
        id="rec-4",
        study_id=study.id,
        name="Sarvam fail test",
        name_normalized=normalize_recording_name("Sarvam fail test"),
        description="",
        original_filename="clip.mp3",
        content_type="audio/mpeg",
        storage_folder=storage_folder,
        storage_path=str(audio_path),
        size_bytes=10,
        transcription_status="queued",
        transcription_job_ref="job-xyz",
        created_at=now,
        updated_at=now,
    )
    db.add(recording)
    db.commit()

    class FakeSarvam:
        provider_name = "sarvam"

        def poll(self, _job_ref):
            return PollResult(status="failed", error="Sarvam transcription failed")

    mock_get_provider.return_value = FakeSarvam()

    from structlog.testing import capture_logs

    with capture_logs() as captured:
        process_recording_transcription("rec-4")

    updated = db.get(AudioRecording, "rec-4")
    assert updated is not None
    assert updated.transcription_status == "failed"
    assert updated.transcription_error == "Sarvam transcription failed"

    assert any(
        entry.get("event") == "transcription_failed"
        and entry.get("recording_id") == "rec-4"
        and entry.get("provider") == "sarvam"
        and entry.get("job_id") == "job-xyz"
        and entry.get("reason") == "provider_reported_failure"
        for entry in captured
    )
