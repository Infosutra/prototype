"""Read and write transcription JSON artifacts on disk."""

from __future__ import annotations

import json
from typing import Any

from app.services.audio_storage import speaker_labels_path, transcript_path, transcript_raw_path


def _load_json(path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def save_transcripts(
    storage_folder: str,
    *,
    normalized: dict[str, Any],
    raw: dict[str, Any],
) -> None:
    transcript_path(storage_folder).write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    transcript_raw_path(storage_folder).write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_transcript(storage_folder: str) -> dict[str, Any] | None:
    return _load_json(transcript_path(storage_folder))


def load_transcript_raw(storage_folder: str) -> dict[str, Any] | None:
    return _load_json(transcript_raw_path(storage_folder))


def load_speaker_labels(storage_folder: str) -> dict[str, str]:
    data = _load_json(speaker_labels_path(storage_folder))
    if not data:
        return {}
    return {str(key): str(value) for key, value in data.items() if value}


def save_speaker_labels(storage_folder: str, labels: dict[str, str]) -> dict[str, str]:
    cleaned = {
        str(key): value.strip()
        for key, value in labels.items()
        if value and value.strip()
    }
    path = speaker_labels_path(storage_folder)
    if cleaned:
        path.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif path.is_file():
        path.unlink()
    return cleaned


def clear_transcripts(storage_folder: str) -> None:
    for path in (
        transcript_path(storage_folder),
        transcript_raw_path(storage_folder),
        speaker_labels_path(storage_folder),
    ):
        if path.is_file():
            path.unlink()
