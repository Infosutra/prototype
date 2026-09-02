"""Factory for transcription providers."""

from __future__ import annotations

from app.db.models import AppSettings
from app.integrations.transcription.base import TranscriptionProvider
from app.integrations.transcription.sarvam import SarvamProvider
from app.integrations.transcription.whisper import WhisperProvider
from app.services import settings as settings_service


def get_transcription_provider(row: AppSettings) -> TranscriptionProvider:
    provider = (row.transcription_provider or "sarvam").strip().lower()
    api_key = settings_service.get_transcription_api_key(row)
    base_url = (row.transcription_base_url or "").strip()
    model = (row.transcription_model or "").strip()

    if provider == "whisper":
        return WhisperProvider(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            model=model or "whisper-1",
        )

    return SarvamProvider(
        api_key=api_key,
        base_url=base_url or "https://api.sarvam.ai",
        model=model or "saaras:v3",
    )
