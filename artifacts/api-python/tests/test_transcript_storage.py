"""Tests for transcript file storage."""

from __future__ import annotations

from app.services.audio_storage import build_storage_folder
from app.services.transcript_storage import (
    clear_transcripts,
    load_speaker_labels,
    load_transcript,
    save_speaker_labels,
    save_transcripts,
)


def _folder() -> str:
    return build_storage_folder(
        study_name="Audio Study",
        study_id="study-audio",
        recording_name="Interview 1",
    )


def test_save_load_and_clear_transcripts(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    storage_folder = _folder()

    save_transcripts(
        storage_folder,
        normalized={"fullText": "hello", "segments": []},
        raw={"provider": "sarvam"},
    )

    assert load_transcript(storage_folder) == {"fullText": "hello", "segments": []}

    clear_transcripts(storage_folder)
    assert load_transcript(storage_folder) is None


def test_save_and_load_speaker_labels(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path)
    storage_folder = _folder()

    saved = save_speaker_labels(storage_folder, {"0": "Enumerator", "1": "  Farmer  "})
    assert saved == {"0": "Enumerator", "1": "Farmer"}
    assert load_speaker_labels(storage_folder) == saved

    save_speaker_labels(storage_folder, {})
    assert load_speaker_labels(storage_folder) == {}
