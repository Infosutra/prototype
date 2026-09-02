from __future__ import annotations

from app.schemas.common import CamelModel


class TranscriptSegmentOut(CamelModel):
    speaker_id: str | None = None
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptOut(CamelModel):
    language_code: str | None = None
    full_text: str
    segments: list[TranscriptSegmentOut] = []
    speaker_labels: dict[str, str] = {}
    segment_layout: str = "linear"


class SpeakerLabelsUpdate(CamelModel):
    labels: dict[str, str] = {}


class AudioRecordingOut(CamelModel):
    id: str
    study_id: str
    name: str
    description: str
    original_filename: str
    content_type: str
    size_bytes: int
    duration_seconds: float | None = None
    transcription_status: str
    transcription_provider: str | None = None
    transcription_language: str | None = None
    transcription_error: str | None = None
    transcript: TranscriptOut | None = None
    transcribed_at: str | None = None
    file_url: str
    transcription_cost_amount: float | None = None
    transcription_cost_currency: str | None = None
    transcription_model: str | None = None
    estimated_transcription_cost_amount: float | None = None
    estimated_transcription_cost_currency: str | None = None
    estimated_transcription_duration_seconds: float | None = None
    transcription_rate_per_minute: float | None = None
    created_at: str
    updated_at: str


class AudioRecordingSummary(CamelModel):
    id: str
    study_id: str
    name: str
    description: str
    original_filename: str
    content_type: str
    size_bytes: int
    duration_seconds: float | None = None
    transcription_status: str
    transcription_provider: str | None = None
    transcription_language: str | None = None
    transcription_error: str | None = None
    transcribed_at: str | None = None
    file_url: str
    transcription_cost_amount: float | None = None
    transcription_cost_currency: str | None = None
    estimated_transcription_cost_amount: float | None = None
    estimated_transcription_cost_currency: str | None = None
    estimated_transcription_duration_seconds: float | None = None
    transcription_rate_per_minute: float | None = None
    created_at: str
    updated_at: str


class AudioRecordingUpdate(CamelModel):
    name: str | None = None
    description: str | None = None


class TranscribeRequest(CamelModel):
    language_code: str | None = None


class UsageEventOut(CamelModel):
    id: str
    occurred_at: str
    category: str
    provider: str
    operation: str
    quantity: float
    unit: str
    amount: float
    currency: str
    study_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict | None = None


class UsageSummaryItem(CamelModel):
    category: str
    total_amount: float
    currency: str
    event_count: int


class UsageSummaryOut(CamelModel):
    items: list[UsageSummaryItem]
    total_amount: float
    currency: str
