"""Tests for diarized segment overlap resolution."""

from __future__ import annotations

from app.integrations.transcription.base import TranscriptSegment
from app.services.transcript_segments import apply_segment_layout, resolve_overlapping_segments


def _has_overlaps(segments: list[TranscriptSegment]) -> bool:
    ordered = sorted(segments, key=lambda segment: segment.start_seconds)
    for index in range(1, len(ordered)):
        previous = ordered[index - 1]
        current = ordered[index]
        if current.start_seconds < previous.end_seconds - 1e-3:
            return True
    return False


def test_resolve_overlapping_segments_splits_long_block_around_interjections():
    segments = [
        TranscriptSegment(
            speaker_id="1",
            start_seconds=736.91,
            end_seconds=757.85,
            text="Kiran long monologue.",
        ),
        TranscriptSegment(
            speaker_id="2",
            start_seconds=741.83,
            end_seconds=742.81,
            text="हाँ हाँ।",
        ),
        TranscriptSegment(
            speaker_id="2",
            start_seconds=744.07,
            end_seconds=744.43,
            text="हाँ।",
        ),
        TranscriptSegment(
            speaker_id="2",
            start_seconds=745.21,
            end_seconds=745.57,
            text="हाँ।",
        ),
    ]

    resolved = resolve_overlapping_segments(segments)

    assert not _has_overlaps(resolved)
    assert resolved[0].speaker_id == "1"
    assert resolved[0].start_seconds == 736.91
    assert resolved[0].end_seconds == 741.83
    assert resolved[1].speaker_id == "2"
    assert resolved[1].start_seconds == 741.83
    assert resolved[1].end_seconds == 742.81
    assert resolved[-1].speaker_id == "1"
    assert resolved[-1].end_seconds == 757.85


def test_apply_segment_layout_provider_preserves_order():
    segments = [
        TranscriptSegment("1", 10.0, 20.0, "long"),
        TranscriptSegment("2", 12.0, 13.0, "short"),
    ]

    provider = apply_segment_layout(segments, "provider")
    linear = apply_segment_layout(segments, "linear")

    assert len(provider) == 2
    assert provider[0].text == "long"
    assert len(linear) > len(provider)


def test_resolve_overlapping_segments_preserves_non_overlapping_input():
    segments = [
        TranscriptSegment(
            speaker_id="0",
            start_seconds=0.1,
            end_seconds=1.2,
            text="Hello.",
        ),
        TranscriptSegment(
            speaker_id="1",
            start_seconds=1.5,
            end_seconds=3.0,
            text="How are you?",
        ),
    ]

    resolved = resolve_overlapping_segments(segments)

    assert len(resolved) == 2
    assert resolved[0].text == "Hello."
    assert resolved[1].text == "How are you?"
    assert not _has_overlaps(resolved)
