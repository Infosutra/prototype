"""Tests for audio storage path helpers."""

from __future__ import annotations

from app.services.audio_storage import (
    build_storage_folder,
    locate_recording_source,
    normalize_recording_name,
    playback_media_type,
    playback_response_headers,
    slugify,
)


def test_slugify_basic():
    assert slugify("Sightsavers 2030") == "sightsavers-2030"
    assert slugify("Kiran Gautam 1999-2000") == "kiran-gautam-1999-2000"


def test_build_storage_folder():
    assert (
        build_storage_folder(
            study_name="Sightsavers 2030",
            study_id="study-sightsavers-2030",
            recording_name="Kiran Gautam 1999-2000",
        )
        == "sightsavers-2030/kiran-gautam-1999-2000"
    )


def test_normalize_recording_name_is_case_insensitive():
    assert normalize_recording_name(" Interview 1 ") == "interview 1"


def test_playback_media_type_normalizes_browser_aliases():
    assert playback_media_type("audio/mp3") == "audio/mpeg"
    assert playback_media_type("audio/x-m4a", "clip.m4a") == "audio/mp4"
    assert playback_media_type("application/octet-stream", "talk.wav") == "audio/wav"


def test_playback_response_headers_supports_ranges_by_default():
    headers = playback_response_headers()
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["Content-Disposition"] == "inline"


def test_playback_response_headers_include_length_and_type():
    headers = playback_response_headers(content_length=1024, content_type="audio/mpeg")
    assert headers["Accept-Ranges"] == "bytes"
    assert headers["Content-Length"] == "1024"
    assert headers["Content-Type"] == "audio/mpeg"


def test_locate_recording_source_uses_storage_folder_when_absolute_path_differs(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("app.services.audio_storage.audio_dir", lambda: tmp_path / "audio")
    storage_folder = "sightsavers-2030/kiran-gautam-1999-2000"
    folder = tmp_path / "audio" / storage_folder
    folder.mkdir(parents=True)
    source = folder / "source.mp3"
    source.write_bytes(b"fake-audio")

    laptop_path = (
        "/home/sarath/work/Infosutra/Data-Insights-Hub/data/audio/"
        f"{storage_folder}/source.mp3"
    )
    resolved = locate_recording_source(
        storage_folder=storage_folder,
        storage_path=laptop_path,
        original_filename="clip.mp3",
        content_type="audio/mpeg",
    )
    assert resolved == source
