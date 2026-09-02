"""Tests for transcript PDF font routing."""

from __future__ import annotations

from app.rendering.transcript_pdf_fonts import (
    markup_mixed_text,
    register_transcript_pdf_fonts,
)


def test_markup_mixed_text_routes_indian_scripts():
    register_transcript_pdf_fonts()
    html = markup_mixed_text("Hello मराठी નમસ્તે తెలుగు")
    assert "TranscriptLatin" in html
    assert "TranscriptDevanagari" in html
    assert "TranscriptGujarati" in html
    assert "TranscriptTelugu" in html
