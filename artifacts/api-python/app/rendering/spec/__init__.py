"""Deterministic rendering of Report Specifications.

One specification plus one resolved dataset renders identically every time, into
HTML, PDF, DOCX or plaintext. Models never emit markup, styles, or chart code.
"""

from app.rendering.spec.base import RenderPayload, format_value, highlight_matches
from app.rendering.spec.docx import render_spec_docx
from app.rendering.spec.html import HTML_RENDERERS, render_spec_html, render_spec_plaintext
from app.rendering.spec.pdf import render_spec_pdf

#: Component types this renderer can draw. Kept in sync with the spec vocabulary by
#: `tests/test_spec_renderer.py`.
SUPPORTED_COMPONENTS = frozenset(HTML_RENDERERS)

__all__ = [
    "HTML_RENDERERS",
    "RenderPayload",
    "SUPPORTED_COMPONENTS",
    "format_value",
    "highlight_matches",
    "render_spec_docx",
    "render_spec_html",
    "render_spec_pdf",
    "render_spec_plaintext",
]
