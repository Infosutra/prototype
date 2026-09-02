"""Tests for transcription provider normalization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.integrations.transcription.sarvam import (
    SarvamProvider,
    azure_presigned_upload_headers,
    normalize_sarvam_model,
)
from app.integrations.transcription.whisper import WhisperProvider


def test_sarvam_normalize_model_aliases():
    assert normalize_sarvam_model("saaras:v3") == "saaras:v3"
    assert normalize_sarvam_model("saaras-v3") == "saaras:v3"
    assert normalize_sarvam_model("saaras:v4") == "saaras:v4"
    assert normalize_sarvam_model("") == "saaras:v3"


def test_azure_presigned_upload_headers():
    headers = azure_presigned_upload_headers(Path("sample.mp3"))
    assert headers["x-ms-blob-type"] == "BlockBlob"
    assert headers["Content-Type"] == "audio/mpeg"


def test_sarvam_submit_uploads_with_azure_headers(tmp_path):
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    job = MagicMock()
    job.job_id = "job-123"

    upload_link = MagicMock()
    upload_link.file_url = "https://example.blob.core.windows.net/container/sample.mp3?sas=token"

    upload_response = MagicMock()
    upload_response.status_code = 201
    upload_response.text = ""

    stt_client = MagicMock()
    stt_client.create_job.return_value = job
    stt_client.get_upload_links.return_value.upload_urls = {"sample.mp3": upload_link}

    client = MagicMock()
    client.speech_to_text_job = stt_client

    provider = SarvamProvider(api_key="test-key")
    with (
        patch.object(provider, "_client", return_value=client),
        patch("app.integrations.transcription.sarvam.httpx.Client") as mock_client_cls,
    ):
        mock_http = MagicMock()
        mock_http.__enter__.return_value = mock_http
        mock_http.put.return_value = upload_response
        mock_client_cls.return_value = mock_http

        job_ref = provider.submit(str(audio_path), language_code="hi-IN")

    assert job_ref.job_id == "job-123"
    stt_client.create_job.assert_called_once()
    kwargs = stt_client.create_job.call_args.kwargs
    assert kwargs["model"] == "saaras:v3"
    assert kwargs["with_diarization"] is True
    assert kwargs["language_code"] == "hi-IN"
    stt_client.get_upload_links.assert_called_once_with(
        job_id="job-123",
        files=["sample.mp3"],
    )
    mock_http.put.assert_called_once()
    put_kwargs = mock_http.put.call_args.kwargs
    assert put_kwargs["headers"]["x-ms-blob-type"] == "BlockBlob"
    assert put_kwargs["headers"]["Content-Type"] == "audio/mpeg"
    assert put_kwargs["content"] == b"fake-audio"
    job.start.assert_called_once()


def test_sarvam_poll_pending():
    status = MagicMock()
    status.job_state = "Running"
    status.error_message = None
    status.model_dump.return_value = {"job_state": "Running"}

    job = MagicMock()
    job.get_status.return_value = status
    job.is_failed.return_value = False

    client = MagicMock()
    client.speech_to_text_job.get_job.return_value = job

    provider = SarvamProvider(api_key="test-key")
    with patch.object(provider, "_client", return_value=client):
        from app.integrations.transcription.base import JobRef

        result = provider.poll(JobRef(provider="sarvam", job_id="job-123"))

    assert result.status == "pending"


def test_sarvam_normalize_diarized_segments():
    provider = SarvamProvider(api_key="test")
    raw = {
        "primary": {
            "transcript": "Hello. How are you?",
            "language_code": "hi-IN",
            "diarized_transcript": {
                "entries": [
                    {
                        "transcript": "Hello.",
                        "start_time_seconds": 0.1,
                        "end_time_seconds": 1.2,
                        "speaker_id": "0",
                    },
                    {
                        "transcript": "How are you?",
                        "start_time_seconds": 1.5,
                        "end_time_seconds": 3.0,
                        "speaker_id": "1",
                    },
                ]
            },
        }
    }
    transcript, usage = provider.normalize(raw)
    assert transcript.language_code == "hi-IN"
    assert transcript.full_text == "Hello. How are you?"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].speaker_id == "0"
    assert transcript.segments[1].text == "How are you?"
    assert usage is not None
    assert usage.quantity == 3.0
    assert usage.unit == "audio_seconds"


def test_sarvam_normalize_chunk_timestamps_fallback():
    provider = SarvamProvider(api_key="test")
    raw = {
        "primary": {
            "transcript": "First chunk. Second chunk.",
            "language_code": "en-IN",
            "timestamps": {
                "chunks": ["First chunk.", "Second chunk."],
                "start_time_seconds": [0.0, 2.0],
                "end_time_seconds": [1.8, 4.5],
            },
        }
    }
    transcript, _usage = provider.normalize(raw)
    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "First chunk."
    assert transcript.segments[1].end_seconds == 4.5


def test_whisper_normalize_verbose_json():
    provider = WhisperProvider(api_key="test")
    raw = {
        "text": "Hello world",
        "language": "en",
        "duration": 5.5,
        "segments": [
            {"start": 0.0, "end": 2.5, "text": " Hello"},
            {"start": 2.5, "end": 5.5, "text": " world"},
        ],
    }
    transcript, usage = provider.normalize(raw)
    assert transcript.full_text == "Hello world"
    assert transcript.language_code == "en"
    assert len(transcript.segments) == 2
    assert transcript.segments[0].speaker_id is None
    assert usage is not None
    assert usage.quantity == 5.5
