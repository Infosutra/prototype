"""Tests for audio duration probing."""

from __future__ import annotations

import wave
from pathlib import Path

from app.services.audio_duration import probe_audio_duration_seconds


def _write_silent_wav(path: Path, *, duration_seconds: float, frame_rate: int = 8000) -> None:
    frame_count = int(duration_seconds * frame_rate)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(frame_rate)
        handle.writeframes(b"\x00\x00" * frame_count)


def test_probe_wav_duration(tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    _write_silent_wav(audio_path, duration_seconds=2.5)

    duration = probe_audio_duration_seconds(audio_path)

    assert duration is not None
    assert abs(duration - 2.5) < 0.01


def test_probe_missing_file_returns_none(tmp_path: Path) -> None:
    assert probe_audio_duration_seconds(tmp_path / "missing.wav") is None
