"""Normalize diarized transcript segments for monotonic playback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.integrations.transcription.base import TranscriptSegment

TranscriptSegmentLayout = Literal["linear", "provider"]
DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT: TranscriptSegmentLayout = "linear"

MIN_SEGMENT_SECONDS = 0.05
TIME_EPS = 1e-3


@dataclass
class _Continuation:
    speaker_id: str | None
    start_seconds: float
    end_seconds: float
    text: str


def _split_text_on_trim(
    text: str,
    *,
    start_seconds: float,
    end_seconds: float,
    split_at: float,
) -> tuple[str, str]:
    """Best-effort split of multiline segment text when trimming the end time."""
    duration = end_seconds - start_seconds
    if duration <= TIME_EPS:
        return text, ""

    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) <= 1:
        ratio = (split_at - start_seconds) / duration
        if ratio >= 0.999:
            return text, ""
        if ratio <= 0.001:
            return "", text
        if not text:
            return "", ""
        cut = max(1, min(len(text) - 1, round(len(text) * ratio)))
        return text[:cut].strip(), text[cut:].strip()

    before: list[str] = []
    after: list[str] = []
    for index, line in enumerate(lines):
        line_start = start_seconds + (index / len(lines)) * duration
        line_end = start_seconds + ((index + 1) / len(lines)) * duration
        if line_end <= split_at + TIME_EPS:
            before.append(line)
        elif line_start >= split_at - TIME_EPS:
            after.append(line)
        else:
            before.append(line)
    return "\n".join(before), "\n".join(after)


def _append_segment(
    output: list[TranscriptSegment],
    *,
    speaker_id: str | None,
    start_seconds: float,
    end_seconds: float,
    text: str,
) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    if end_seconds - start_seconds < MIN_SEGMENT_SECONDS:
        return
    output.append(
        TranscriptSegment(
            speaker_id=speaker_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=cleaned,
        )
    )


def _trim_tail_for_overlap(
    output: list[TranscriptSegment],
    continuations: list[_Continuation],
    *,
    split_at: float,
) -> None:
    while output and output[-1].end_seconds > split_at + TIME_EPS:
        previous = output[-1]
        before_text, after_text = _split_text_on_trim(
            previous.text,
            start_seconds=previous.start_seconds,
            end_seconds=previous.end_seconds,
            split_at=split_at,
        )
        output.pop()
        if split_at - previous.start_seconds >= MIN_SEGMENT_SECONDS:
            _append_segment(
                output,
                speaker_id=previous.speaker_id,
                start_seconds=previous.start_seconds,
                end_seconds=split_at,
                text=before_text,
            )
        if after_text.strip():
            continuations.append(
                _Continuation(
                    speaker_id=previous.speaker_id,
                    start_seconds=split_at,
                    end_seconds=previous.end_seconds,
                    text=after_text,
                )
            )


def _interrupt_continuations(
    output: list[TranscriptSegment],
    continuations: list[_Continuation],
    segment: TranscriptSegment,
) -> None:
    """Emit continuation audio before an interrupt and resume after it ends."""
    remaining: list[_Continuation] = []
    for continuation in continuations:
        if continuation.speaker_id == segment.speaker_id:
            remaining.append(continuation)
            continue

        if continuation.end_seconds <= segment.start_seconds + TIME_EPS:
            _append_segment(
                output,
                speaker_id=continuation.speaker_id,
                start_seconds=continuation.start_seconds,
                end_seconds=continuation.end_seconds,
                text=continuation.text,
            )
            continue

        if continuation.start_seconds >= segment.end_seconds - TIME_EPS:
            remaining.append(continuation)
            continue

        if segment.start_seconds > continuation.start_seconds + TIME_EPS:
            before_text, after_text = _split_text_on_trim(
                continuation.text,
                start_seconds=continuation.start_seconds,
                end_seconds=continuation.end_seconds,
                split_at=segment.start_seconds,
            )
            _append_segment(
                output,
                speaker_id=continuation.speaker_id,
                start_seconds=continuation.start_seconds,
                end_seconds=segment.start_seconds,
                text=before_text,
            )
            if after_text.strip():
                remaining.append(
                    _Continuation(
                        speaker_id=continuation.speaker_id,
                        start_seconds=segment.end_seconds,
                        end_seconds=continuation.end_seconds,
                        text=after_text,
                    )
                )
            continue

        before_text, after_text = _split_text_on_trim(
            continuation.text,
            start_seconds=continuation.start_seconds,
            end_seconds=continuation.end_seconds,
            split_at=segment.end_seconds,
        )
        if after_text.strip():
            remaining.append(
                _Continuation(
                    speaker_id=continuation.speaker_id,
                    start_seconds=segment.end_seconds,
                    end_seconds=continuation.end_seconds,
                    text=after_text,
                )
            )

    continuations.clear()
    continuations.extend(remaining)


def resolve_overlapping_segments(
    segments: list[TranscriptSegment],
) -> list[TranscriptSegment]:
    """
    Trim/split overlapping diarization segments so playback can advance linearly.

    Sarvam diarization can return long speaker blocks whose end times span shorter
    interjections from another speaker. This pass trims those blocks and reinserts
    the remainder after the interrupts.
    """
    if not segments:
        return []

    ordered = sorted(segments, key=lambda segment: (segment.start_seconds, segment.end_seconds))
    output: list[TranscriptSegment] = []
    continuations: list[_Continuation] = []

    for segment in ordered:
        start = segment.start_seconds
        end = segment.end_seconds
        if end <= start + MIN_SEGMENT_SECONDS:
            continue

        _trim_tail_for_overlap(output, continuations, split_at=start)
        _interrupt_continuations(output, continuations, segment)
        _append_segment(
            output,
            speaker_id=segment.speaker_id,
            start_seconds=start,
            end_seconds=end,
            text=segment.text,
        )

    for continuation in continuations:
        _append_segment(
            output,
            speaker_id=continuation.speaker_id,
            start_seconds=continuation.start_seconds,
            end_seconds=continuation.end_seconds,
            text=continuation.text,
        )

    return sorted(output, key=lambda segment: (segment.start_seconds, segment.end_seconds))


def apply_segment_layout(
    segments: list[TranscriptSegment],
    layout: TranscriptSegmentLayout = DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT,
) -> list[TranscriptSegment]:
    """Return transcript segments in the requested presentation layout."""
    if layout == "provider":
        return list(segments)
    return resolve_overlapping_segments(segments)


def normalize_segment_layout(value: str | None) -> TranscriptSegmentLayout:
    if value == "provider":
        return "provider"
    return DEFAULT_TRANSCRIPT_SEGMENT_LAYOUT
