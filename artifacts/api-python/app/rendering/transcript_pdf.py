"""PDF rendering for diarized audio transcripts."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.rendering.transcript_pdf_fonts import (
    latin_font_name,
    markup_latin,
    markup_mixed_text,
    register_transcript_pdf_fonts,
)
from app.services.transcript_export import (
    TranscriptExportContext,
    format_duration_minutes,
    format_timestamp,
)

_NAVY = colors.HexColor("#1A365D")
_LABEL_FILL = colors.HexColor("#E8F0FE")


def _metadata_rows(context: TranscriptExportContext) -> list[tuple[str, str]]:
    provider = (context.transcription_provider or "—").upper()
    if context.transcription_model:
        provider = f"{provider} ({context.transcription_model})"

    cost = "—"
    if context.transcription_cost_amount is not None and context.transcription_cost_amount > 0:
        cost = (
            f"{context.transcription_cost_currency or 'INR'} "
            f"{context.transcription_cost_amount:.2f}"
        )

    rows = [
        ("Source File", context.original_filename),
        ("Total Utterances", f"{context.total_utterances:,}"),
        ("Speakers", context.speaker_stats),
        ("Study", context.study_name),
        ("Transcription Provider", provider),
        ("Language", context.transcription_language or "—"),
        ("Words", f"{context.word_count:,}"),
        ("Transcription Cost", cost),
        ("Transcribed", context.transcribed_at or "—"),
        ("Exported", context.exported_at),
    ]
    if context.description.strip():
        rows.insert(3, ("Description", context.description.strip()))
    return rows


def _segment_line(segment: dict) -> str:
    time_range = (
        f"[{format_timestamp(segment['start_seconds'])} – "
        f"{format_timestamp(segment['end_seconds'])}]"
    )
    prefix = f"{time_range} {segment['speaker']}: "
    return f"{markup_latin(prefix, bold=True)}{markup_mixed_text(segment['text'])}"


def render_transcript_pdf(context: TranscriptExportContext) -> bytes:
    register_transcript_pdf_fonts()
    latin_font = latin_font_name()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"Transcript — {context.recording_name}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TranscriptTitle",
        parent=styles["Heading1"],
        fontName=latin_font,
        fontSize=16,
        leading=20,
        textColor=_NAVY,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "TranscriptSubtitle",
        parent=styles["Normal"],
        fontName=latin_font,
        fontSize=10,
        leading=13,
        textColor=_NAVY,
        spaceAfter=8,
    )
    label_style = ParagraphStyle(
        "TranscriptLabel",
        parent=styles["Normal"],
        fontName=latin_font,
        fontSize=8.5,
        leading=11,
        textColor=_NAVY,
    )
    value_style = ParagraphStyle(
        "TranscriptValue",
        parent=styles["Normal"],
        fontName=latin_font,
        fontSize=8.5,
        leading=11,
    )
    section_style = ParagraphStyle(
        "TranscriptSection",
        parent=styles["Heading2"],
        fontName=latin_font,
        fontSize=11,
        leading=14,
        textColor=_NAVY,
        spaceBefore=10,
        spaceAfter=6,
    )
    segment_style = ParagraphStyle(
        "TranscriptSegment",
        parent=styles["Normal"],
        fontName=latin_font,
        fontSize=8.5,
        leading=12,
        spaceAfter=4,
    )

    title = f"Transcript — {context.recording_name}"
    subtitle = (
        f"{context.study_name} | {context.transcribed_at or '—'} | "
        f"{format_duration_minutes(context.duration_seconds)}"
    )

    story: list = [
        Paragraph(markup_latin(title, bold=True), title_style),
        Paragraph(markup_latin(subtitle, bold=True), subtitle_style),
        Spacer(1, 4),
    ]

    label_col_width = 44 * mm
    value_col_width = doc.width - label_col_width
    table_data = [
        [
            Paragraph(markup_latin(label, bold=True), label_style),
            Paragraph(markup_mixed_text(value), value_style),
        ]
        for label, value in _metadata_rows(context)
    ]
    table = Table(table_data, colWidths=[label_col_width, value_col_width], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), _LABEL_FILL),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 10),
            Paragraph(markup_latin("Diarized transcript", bold=True), section_style),
        ]
    )

    for segment in context.segments:
        story.append(Paragraph(_segment_line(segment), segment_style))

    doc.build(story)
    return buffer.getvalue()
