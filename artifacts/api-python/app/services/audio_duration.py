"""Probe audio file duration from disk."""

from __future__ import annotations

import wave
from pathlib import Path


def probe_audio_duration_seconds(path: str | Path) -> float | None:
    audio_path = Path(path)
    if not audio_path.is_file():
        return None

    suffix = audio_path.suffix.lower()
    if suffix == ".wav":
        try:
            with wave.open(str(audio_path), "rb") as handle:
                frame_rate = handle.getframerate()
                frame_count = handle.getnframes()
                if frame_rate > 0 and frame_count > 0:
                    return frame_count / float(frame_rate)
        except wave.Error:
            return None

    try:
        from mutagen import File as MutagenFile
    except ImportError:
        return None

    try:
        audio = MutagenFile(str(audio_path))
    except Exception:
        return None

    if audio is None or audio.info is None:
        return None
    length = getattr(audio.info, "length", None)
    if length is None:
        return None
    duration = float(length)
    return duration if duration > 0 else None
