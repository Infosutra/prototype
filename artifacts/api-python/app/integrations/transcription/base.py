"""Transcription provider protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass
class TranscriptSegment:
    speaker_id: str | None
    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class Transcript:
    language_code: str | None
    full_text: str
    segments: list[TranscriptSegment] = field(default_factory=list)


@dataclass
class UsageHint:
    quantity: float
    unit: str
    amount: float | None = None
    currency: str = "INR"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobRef:
    provider: str
    job_id: str
    extra: dict[str, Any] = field(default_factory=dict)


PollStatus = Literal["pending", "succeeded", "failed"]


@dataclass
class PollResult:
    status: PollStatus
    raw: dict[str, Any] | None = None
    error: str | None = None


class TranscriptionProvider(Protocol):
    provider_name: str

    def submit(self, audio_path: str, *, language_code: str | None = None) -> JobRef:
        """Start async transcription; returns a job reference for polling."""

    def poll(self, job_ref: JobRef) -> PollResult:
        """Check job status; when succeeded, raw contains provider payload."""

    def normalize(self, raw: dict[str, Any]) -> tuple[Transcript, UsageHint | None]:
        """Convert provider payload to normalized transcript + optional usage hint."""

    def transcribe_sync(
        self, audio_path: str, *, language_code: str | None = None
    ) -> tuple[dict[str, Any], Transcript, UsageHint | None]:
        """Synchronous path for providers that do not need polling (e.g. Whisper)."""


def transcript_to_dict(transcript: Transcript) -> dict[str, Any]:
    return {
        "languageCode": transcript.language_code,
        "fullText": transcript.full_text,
        "segments": [
            {
                "speakerId": seg.speaker_id,
                "startSeconds": seg.start_seconds,
                "endSeconds": seg.end_seconds,
                "text": seg.text,
            }
            for seg in transcript.segments
        ],
    }
