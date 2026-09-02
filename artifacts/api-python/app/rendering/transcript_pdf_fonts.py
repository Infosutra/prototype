"""Font registration and script-aware text markup for transcript PDFs."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

_ASSETS_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_NOTO_DIR = Path("/usr/share/fonts/truetype/noto")

_LATIN_FONT = "TranscriptLatin"
_LATIN_BOLD_FONT = "TranscriptLatinBold"

_FONTS_REGISTERED = False
_LATIN_BOLD_AVAILABLE = False
_REGISTERED_SCRIPT_FONT_NAMES: set[str] = set()


@dataclass(frozen=True)
class ScriptFontSpec:
    font_name: str
    start: int
    end: int
    bundled_file: str
    system_file: str

    @property
    def pattern(self) -> re.Pattern[str]:
        return re.compile(rf"[{chr(self.start)}-{chr(self.end)}]+")


# Indian scripts supported in transcript PDF exports.
# Marathi/Hindi/Konkani/Nepali share Devanagari with Hindi.
SCRIPT_FONTS: tuple[ScriptFontSpec, ...] = (
    ScriptFontSpec("TranscriptDevanagari", 0x0900, 0x097F, "NotoSansDevanagari-Regular.ttf", "NotoSansDevanagari-Regular.ttf"),
    ScriptFontSpec("TranscriptBengali", 0x0980, 0x09FF, "NotoSansBengali-Regular.ttf", "NotoSansBengali-Regular.ttf"),
    ScriptFontSpec("TranscriptGurmukhi", 0x0A00, 0x0A7F, "NotoSansGurmukhi-Regular.ttf", "NotoSansGurmukhi-Regular.ttf"),
    ScriptFontSpec("TranscriptGujarati", 0x0A80, 0x0AFF, "NotoSansGujarati-Regular.ttf", "NotoSansGujarati-Regular.ttf"),
    ScriptFontSpec("TranscriptOriya", 0x0B00, 0x0B7F, "NotoSansOriya-Regular.ttf", "NotoSansOriya-Regular.ttf"),
    ScriptFontSpec("TranscriptTamil", 0x0B80, 0x0BFF, "NotoSansTamil-Regular.ttf", "NotoSansTamil-Regular.ttf"),
    ScriptFontSpec("TranscriptTelugu", 0x0C00, 0x0C7F, "NotoSansTelugu-Regular.ttf", "NotoSansTelugu-Regular.ttf"),
    ScriptFontSpec("TranscriptKannada", 0x0C80, 0x0CFF, "NotoSansKannada-Regular.ttf", "NotoSansKannada-Regular.ttf"),
    ScriptFontSpec("TranscriptMalayalam", 0x0D00, 0x0D7F, "NotoSansMalayalam-Regular.ttf", "NotoSansMalayalam-Regular.ttf"),
)

_INDIC_RUN_RE = re.compile(
    "[" + "".join(chr(spec.start) + "-" + chr(spec.end) for spec in SCRIPT_FONTS) + "]+"
)


def _first_existing(*paths: Path) -> Path | None:
    for path in paths:
        if path.is_file():
            return path
    return None


def _register_font_family(font_name: str) -> None:
    from reportlab.pdfbase.pdfmetrics import registerFontFamily

    registerFontFamily(
        font_name,
        normal=font_name,
        bold=font_name,
        italic=font_name,
        boldItalic=font_name,
    )


def register_transcript_pdf_fonts() -> None:
    global _FONTS_REGISTERED, _LATIN_BOLD_AVAILABLE, _REGISTERED_SCRIPT_FONT_NAMES
    if _FONTS_REGISTERED:
        return

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    from reportlab.pdfbase.ttfonts import TTFont

    latin_regular = _first_existing(
        _ASSETS_FONTS / "NotoSans-Regular.ttf",
        _NOTO_DIR / "NotoSans-Regular.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    )
    latin_bold = _first_existing(
        _ASSETS_FONTS / "NotoSans-Bold.ttf",
        _NOTO_DIR / "NotoSans-Bold.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    )
    if latin_regular is None:
        raise RuntimeError("No Latin font found for transcript PDF export")

    pdfmetrics.registerFont(TTFont(_LATIN_FONT, str(latin_regular)))
    _LATIN_BOLD_AVAILABLE = latin_bold is not None
    if latin_bold is not None:
        pdfmetrics.registerFont(TTFont(_LATIN_BOLD_FONT, str(latin_bold)))
        registerFontFamily(
            _LATIN_FONT,
            normal=_LATIN_FONT,
            bold=_LATIN_BOLD_FONT,
            italic=_LATIN_FONT,
            boldItalic=_LATIN_BOLD_FONT,
        )
    else:
        registerFontFamily(
            _LATIN_FONT,
            normal=_LATIN_FONT,
            bold=_LATIN_FONT,
            italic=_LATIN_FONT,
            boldItalic=_LATIN_FONT,
        )

    registered_names: set[str] = set()
    for spec in SCRIPT_FONTS:
        font_path = _first_existing(
            _ASSETS_FONTS / spec.bundled_file,
            _NOTO_DIR / spec.system_file,
            Path(f"/usr/share/fonts/opentype/noto/{spec.system_file}"),
        )
        if font_path is None:
            continue
        pdfmetrics.registerFont(TTFont(spec.font_name, str(font_path)))
        _register_font_family(spec.font_name)
        registered_names.add(spec.font_name)

    _REGISTERED_SCRIPT_FONT_NAMES = registered_names
    _FONTS_REGISTERED = True


def latin_font_name() -> str:
    return _LATIN_FONT


def _script_font_for_char(char: str) -> str | None:
    if not char:
        return None
    code = ord(char)
    for spec in SCRIPT_FONTS:
        if spec.start <= code <= spec.end:
            return spec.font_name if spec.font_name in _REGISTERED_SCRIPT_FONT_NAMES else None
    return None


def _script_font_for_text(text: str) -> str | None:
    for char in text:
        font_name = _script_font_for_char(char)
        if font_name:
            return font_name
    return None


def markup_latin(text: str, *, bold: bool = False) -> str:
    escaped = html.escape(text)
    if bold and _LATIN_BOLD_AVAILABLE:
        return f'<font name="{_LATIN_BOLD_FONT}">{escaped}</font>'
    return f'<font name="{_LATIN_FONT}">{escaped}</font>'


def markup_script(text: str, font_name: str) -> str:
    return f'<font name="{font_name}">{html.escape(text)}</font>'


def markup_mixed_text(text: str) -> str:
    """Render Latin and Indian-script runs with the appropriate fonts."""
    if not text:
        return ""

    parts: list[str] = []
    last = 0
    for match in _INDIC_RUN_RE.finditer(text):
        if match.start() > last:
            parts.append(markup_latin(text[last : match.start()]))
        run = match.group(0)
        font_name = _script_font_for_text(run)
        if font_name:
            parts.append(markup_script(run, font_name))
        else:
            parts.append(markup_latin(run))
        last = match.end()
    if last < len(text):
        parts.append(markup_latin(text[last:]))
    return "".join(parts)
