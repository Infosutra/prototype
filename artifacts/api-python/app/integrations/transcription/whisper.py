"""OpenAI Whisper-compatible transcription provider."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.integrations.transcription.base import (
    JobRef,
    PollResult,
    Transcript,
    TranscriptSegment,
    UsageHint,
)


class WhisperError(Exception):
    pass


class WhisperProvider:
    provider_name = "whisper"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "whisper-1",
        timeout_seconds: float = 300.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds

    def submit(self, audio_path: str, *, language_code: str | None = None) -> JobRef:
        raise NotImplementedError("Whisper uses synchronous transcription")

    def poll(self, job_ref: JobRef) -> PollResult:
        raise NotImplementedError("Whisper uses synchronous transcription")

    def transcribe_sync(
        self, audio_path: str, *, language_code: str | None = None
    ) -> tuple[dict[str, Any], Transcript, UsageHint | None]:
        if not self._api_key:
            raise WhisperError("Whisper API key is not configured")

        path = Path(audio_path)
        if not path.is_file():
            raise WhisperError(f"Audio file not found: {audio_path}")

        url = f"{self._base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        data: dict[str, str] = {
            "model": self._model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language_code:
            data["language"] = language_code.split("-")[0]

        try:
            with path.open("rb") as audio_file:
                response = httpx.post(
                    url,
                    headers=headers,
                    data=data,
                    files={"file": (path.name, audio_file, "application/octet-stream")},
                    timeout=self._timeout,
                )
        except httpx.HTTPError as exc:
            raise WhisperError(f"Whisper request failed: {exc}") from exc

        if response.status_code >= 400:
            raise WhisperError(f"Whisper HTTP {response.status_code}: {response.text[:500]}")

        raw = response.json()
        transcript, usage = self.normalize(raw)
        return raw, transcript, usage

    def normalize(self, raw: dict[str, Any]) -> tuple[Transcript, UsageHint | None]:
        segments: list[TranscriptSegment] = []
        for item in raw.get("segments") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    speaker_id=None,
                    start_seconds=float(item.get("start") or 0.0),
                    end_seconds=float(item.get("end") or 0.0),
                    text=text,
                )
            )

        full_text = str(raw.get("text") or "").strip()
        if not full_text and segments:
            full_text = " ".join(seg.text for seg in segments)

        duration = float(raw.get("duration") or 0.0)
        if not duration and segments:
            duration = max(seg.end_seconds for seg in segments)

        usage = None
        if duration > 0:
            usage = UsageHint(
                quantity=duration,
                unit="audio_seconds",
                metadata={"model": self._model},
            )

        return Transcript(
            language_code=raw.get("language"),
            full_text=full_text,
            segments=segments,
        ), usage
