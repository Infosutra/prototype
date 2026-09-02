"""Filesystem paths for uploaded audio artifacts."""

from __future__ import annotations

import re
import shutil
import unicodedata
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_AUDIO_DIR = _REPO_ROOT / "data" / "audio"

SOURCE_BASENAME = "source"
TRANSCRIPT_FILENAME = "transcript.json"
TRANSCRIPT_RAW_FILENAME = "transcript_raw.json"
SPEAKER_LABELS_FILENAME = "speaker_labels.json"
REPORTS_DIRNAME = "reports"

ALLOWED_CONTENT_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".flac"}

# HTML5 <audio> is picky about Content-Type. Normalize aliases to types browsers accept.
_PLAYBACK_MEDIA_TYPES = {
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/mp4": "audio/mp4",
    "audio/x-m4a": "audio/mp4",
    "audio/ogg": "audio/ogg",
    "audio/webm": "audio/webm",
    "audio/flac": "audio/flac",
    "audio/x-flac": "audio/flac",
}
_PLAYBACK_MEDIA_TYPES_BY_EXT = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
}


def normalize_recording_name(name: str) -> str:
    return name.strip().casefold()


def slugify(value: str, *, fallback: str = "item", max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_text.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    if not slug:
        slug = fallback
    return slug[:max_length].strip("-") or fallback


def build_storage_folder(*, study_name: str, study_id: str, recording_name: str) -> str:
    study_slug = slugify(study_name, fallback=slugify(study_id, fallback="study"))
    recording_slug = slugify(recording_name, fallback="recording")
    return f"{study_slug}/{recording_slug}"


def audio_dir() -> Path:
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return _AUDIO_DIR


def recording_dir(storage_folder: str) -> Path:
    path = audio_dir() / storage_folder
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir(storage_folder: str) -> Path:
    path = recording_dir(storage_folder) / REPORTS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_recording_layout(storage_folder: str) -> Path:
    folder = recording_dir(storage_folder)
    reports_dir(storage_folder)
    return folder


def audio_path_for(storage_folder: str, extension: str) -> Path:
    ext = extension if extension.startswith(".") else f".{extension}"
    ensure_recording_layout(storage_folder)
    return recording_dir(storage_folder) / f"{SOURCE_BASENAME}{ext}"


def transcript_path(storage_folder: str) -> Path:
    return recording_dir(storage_folder) / TRANSCRIPT_FILENAME


def transcript_raw_path(storage_folder: str) -> Path:
    return recording_dir(storage_folder) / TRANSCRIPT_RAW_FILENAME


def speaker_labels_path(storage_folder: str) -> Path:
    return recording_dir(storage_folder) / SPEAKER_LABELS_FILENAME


def playback_media_type(content_type: str, filename: str = "") -> str:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized in _PLAYBACK_MEDIA_TYPES:
        return _PLAYBACK_MEDIA_TYPES[normalized]
    suffix = Path(filename).suffix.lower()
    return _PLAYBACK_MEDIA_TYPES_BY_EXT.get(suffix, "application/octet-stream")


def locate_recording_source(
    *,
    storage_folder: str,
    storage_path: str = "",
    original_filename: str = "",
    content_type: str = "",
) -> Path:
    """Resolve the on-disk source file for a recording.

    Prefer the canonical layout under the current install's audio_dir() so
    databases synced from another machine still find files when absolute
    storage_path values differ (e.g. laptop vs Raspberry Pi deploy roots).
    """
    if storage_folder:
        folder = audio_dir() / storage_folder
        if folder.is_dir():
            if storage_path:
                by_stored_name = folder / Path(storage_path).name
                if by_stored_name.is_file():
                    return by_stored_name
            if original_filename:
                by_upload_name = folder / Path(original_filename).name
                if by_upload_name.is_file():
                    return by_upload_name
            extension = guess_extension(content_type, original_filename or storage_path)
            canonical = folder / f"{SOURCE_BASENAME}{extension}"
            if canonical.is_file():
                return canonical
            for candidate in sorted(folder.glob(f"{SOURCE_BASENAME}.*")):
                if candidate.is_file() and candidate.suffix.lower() in ALLOWED_EXTENSIONS:
                    return candidate

    if storage_path:
        legacy = Path(storage_path)
        if legacy.is_file():
            return legacy

    raise FileNotFoundError(storage_folder or storage_path)


def resolve_recording_file(
    storage_path: str,
    *,
    storage_folder: str = "",
    original_filename: str = "",
    content_type: str = "",
) -> Path:
    return locate_recording_source(
        storage_folder=storage_folder,
        storage_path=storage_path,
        original_filename=original_filename,
        content_type=content_type,
    )


def playback_response_headers(
    *,
    content_length: int | None = None,
    content_type: str | None = None,
) -> dict[str, str]:
    headers = {
        "Content-Disposition": "inline",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=0, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def guess_extension(content_type: str, filename: str) -> str:
    if content_type in ALLOWED_CONTENT_TYPES:
        return ALLOWED_CONTENT_TYPES[content_type]
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return suffix
    return ".mp3"


def delete_recording_assets(storage_folder: str, storage_path: str | None = None) -> None:
    """Remove a recording folder and any legacy flat or uuid-root audio file."""
    folder = audio_dir() / storage_folder
    if folder.is_dir():
        shutil.rmtree(folder, ignore_errors=True)

    if storage_path:
        legacy_file = Path(storage_path)
        if legacy_file.is_file():
            legacy_parent = legacy_file.parent
            legacy_file.unlink(missing_ok=True)
            if legacy_parent.is_dir() and legacy_parent != folder:
                try:
                    if not any(legacy_parent.iterdir()):
                        legacy_parent.rmdir()
                except OSError:
                    pass
