"""Sarvam AI batch speech-to-text provider (official SDK)."""

from __future__ import annotations

import json
import mimetypes
import tempfile
from http import HTTPStatus
from pathlib import Path
from typing import Any

import httpx
from sarvamai import SarvamAI
from sarvamai.speech_to_text_job.client import SpeechToTextJobClient

from app.integrations.transcription.base import JobRef, PollResult, Transcript, TranscriptSegment, UsageHint


class SarvamError(Exception):
    pass


_PENDING_STATES = {"Accepted", "Pending", "Running"}


def normalize_sarvam_model(model: str) -> str:
    """Accept saaras:v3, saaras-v3, saaras:v4, etc. for the Sarvam batch API."""
    value = (model or "").strip()
    if not value:
        return "saaras:v3"
    if ":" in value:
        return value
    if value.startswith("saaras-"):
        return value.replace("saaras-", "saaras:", 1)
    return value


def azure_presigned_upload_headers(path: Path) -> dict[str, str]:
    """Azure Blob presigned PUT URLs require x-ms-blob-type."""
    content_type, _ = mimetypes.guess_type(path.name)
    if not content_type:
        content_type = "application/octet-stream"
    return {
        "x-ms-blob-type": "BlockBlob",
        "Content-Type": content_type,
    }


def _model_dump(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    dict_fn = getattr(value, "dict", None)
    if callable(dict_fn):
        return dict_fn()
    return {}


class SarvamProvider:
    provider_name = "sarvam"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.sarvam.ai",
        model: str = "saaras:v3",
        timeout_seconds: float = 300.0,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._model = normalize_sarvam_model(model)
        self._timeout = timeout_seconds

    def _client(self) -> SarvamAI:
        if not self._api_key:
            raise SarvamError("Sarvam API key is not configured")
        return SarvamAI(api_subscription_key=self._api_key, timeout=self._timeout)

    def _upload_audio_files(
        self,
        stt_client: SpeechToTextJobClient,
        job_id: str,
        paths: list[Path],
    ) -> None:
        upload_links = stt_client.get_upload_links(
            job_id=job_id,
            files=[path.name for path in paths],
        )
        client_timeout = httpx.Timeout(timeout=self._timeout)
        with httpx.Client(timeout=client_timeout) as http:
            for path in paths:
                file_name = path.name
                upload_url = upload_links.upload_urls[file_name].file_url
                response = http.put(
                    upload_url,
                    content=path.read_bytes(),
                    headers=azure_presigned_upload_headers(path),
                )
                if (
                    response.status_code < HTTPStatus.OK
                    or response.status_code > HTTPStatus.IM_USED
                ):
                    body = response.text.strip()[:500]
                    raise SarvamError(
                        f"Sarvam file upload failed HTTP {response.status_code}: {body}"
                    )

    def submit(self, audio_path: str, *, language_code: str | None = None) -> JobRef:
        path = Path(audio_path)
        if not path.is_file():
            raise SarvamError(f"Audio file not found: {audio_path}")

        try:
            client = self._client()
            stt_client = client.speech_to_text_job
            job = stt_client.create_job(
                model=self._model,
                mode="transcribe",
                with_timestamps=True,
                with_diarization=True,
                language_code=language_code or "unknown",
            )
            self._upload_audio_files(stt_client, job.job_id, [path])
            job.start()
        except SarvamError:
            raise
        except Exception as exc:
            raise SarvamError(str(exc)) from exc

        job_id = str(getattr(job, "job_id", "") or "")
        if not job_id:
            raise SarvamError("Sarvam did not return a job_id")

        return JobRef(
            provider=self.provider_name,
            job_id=job_id,
            extra={"filename": path.name, "language_code": language_code},
        )

    def poll(self, job_ref: JobRef) -> PollResult:
        try:
            job = self._client().speech_to_text_job.get_job(job_ref.job_id)
            status = job.get_status()
        except Exception as exc:
            raise SarvamError(str(exc)) from exc

        status_dict = _model_dump(status)
        job_state = str(status_dict.get("job_state") or getattr(status, "job_state", "") or "")

        if job_state in _PENDING_STATES or not job_state:
            return PollResult(status="pending")

        if job_state == "Failed" or getattr(job, "is_failed", lambda: False)():
            error = str(
                status_dict.get("error_message")
                or getattr(status, "error_message", None)
                or "Sarvam transcription failed"
            )
            return PollResult(status="failed", error=error)

        if job_state != "Completed":
            return PollResult(status="pending")

        file_results = job.get_file_results() or {}
        failed = file_results.get("failed") or []
        if failed and not (file_results.get("successful") or []):
            first = failed[0] if isinstance(failed[0], dict) else {}
            return PollResult(
                status="failed",
                error=str(first.get("error_message") or "Sarvam transcription failed"),
            )

        raw_payload: dict[str, Any] = {"status": status_dict, "results": []}
        with tempfile.TemporaryDirectory(prefix="sarvam-stt-") as tmp_dir:
            try:
                job.download_outputs(output_dir=tmp_dir)
            except Exception as exc:
                raise SarvamError(f"Failed to download Sarvam result: {exc}") from exc
            for json_path in sorted(Path(tmp_dir).glob("*.json")):
                try:
                    raw_payload["results"].append(json.loads(json_path.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    raw_payload["results"].append({"text": json_path.read_text(encoding="utf-8")})

        if not raw_payload["results"]:
            return PollResult(status="failed", error="Could not download Sarvam transcription results")

        raw_payload["primary"] = raw_payload["results"][0]
        return PollResult(status="succeeded", raw=raw_payload)

    def normalize(self, raw: dict[str, Any]) -> tuple[Transcript, UsageHint | None]:
        primary = raw.get("primary") or (raw.get("results") or [{}])[0]
        if not isinstance(primary, dict):
            primary = {}

        segments: list[TranscriptSegment] = []
        diarized = primary.get("diarized_transcript") or {}
        entries = diarized.get("entries") if isinstance(diarized, dict) else None

        if isinstance(entries, list) and entries:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                text = str(entry.get("transcript") or "").strip()
                if not text:
                    continue
                segments.append(
                    TranscriptSegment(
                        speaker_id=str(entry.get("speaker_id"))
                        if entry.get("speaker_id") is not None
                        else None,
                        start_seconds=float(entry.get("start_time_seconds") or 0.0),
                        end_seconds=float(entry.get("end_time_seconds") or 0.0),
                        text=text,
                    )
                )
        else:
            timestamps = primary.get("timestamps") or {}
            chunks = timestamps.get("chunks") if isinstance(timestamps, dict) else []
            starts = timestamps.get("start_time_seconds") if isinstance(timestamps, dict) else []
            ends = timestamps.get("end_time_seconds") if isinstance(timestamps, dict) else []
            if isinstance(chunks, list):
                for idx, chunk in enumerate(chunks):
                    text = str(chunk or "").strip()
                    if not text:
                        continue
                    start = float(starts[idx]) if idx < len(starts) else 0.0
                    end = float(ends[idx]) if idx < len(ends) else start
                    segments.append(
                        TranscriptSegment(
                            speaker_id=None,
                            start_seconds=start,
                            end_seconds=end,
                            text=text,
                        )
                    )

        full_text = str(primary.get("transcript") or "").strip()
        if not full_text and segments:
            full_text = " ".join(seg.text for seg in segments)

        duration = 0.0
        if segments:
            duration = max(seg.end_seconds for seg in segments)

        usage = None
        if duration > 0:
            usage = UsageHint(
                quantity=duration,
                unit="audio_seconds",
                metadata={"model": self._model, "provider": self.provider_name},
            )

        return Transcript(
            language_code=primary.get("language_code"),
            full_text=full_text,
            segments=segments,
        ), usage

    def transcribe_sync(
        self, audio_path: str, *, language_code: str | None = None
    ) -> tuple[dict[str, Any], Transcript, UsageHint | None]:
        raise NotImplementedError("Sarvam uses async batch transcription")
