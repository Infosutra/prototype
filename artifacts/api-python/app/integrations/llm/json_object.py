"""Best-effort JSON-object extraction from LLM text, with visible parse failures.

Call sites that previously collapsed empty / malformed / non-object replies into an
indistinguishable ``{}`` should use this helper so operators can see *why* a parse
failed without changing success/failure return values for callers that still want
``result.data or {}``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

import structlog
logger = structlog.stdlib.get_logger(__name__)

#: Truncate raw model text in warning logs so a brace-salad reply cannot flood logs.
JSON_PARSE_LOG_CHARS = 800

JsonObjectParseKind = Literal["ok", "empty", "not_object", "malformed"]


@dataclass(frozen=True)
class JsonObjectParse:
    """Result of extracting a JSON object from model text."""

    data: dict[str, Any] | None = None
    error: str | None = None
    kind: JsonObjectParseKind = "empty"


def parse_json_object(text: str, *, log_label: str = "LLM") -> JsonObjectParse:
    """Parse ``text`` into a JSON object, distinguishing empty from malformed.

    On failure ``data`` is ``None`` and a warning is logged for malformed /
    non-object replies (empty content is returned quietly as ``kind="empty"``).
    """
    stripped = (text or "").strip()
    if not stripped:
        return JsonObjectParse(kind="empty", error="Model returned no content")
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", stripped).strip()
        if not stripped:
            return JsonObjectParse(kind="empty", error="Model returned no content")

    def _fail(exc: json.JSONDecodeError, *, source: str) -> JsonObjectParse:
        snippet = stripped[:JSON_PARSE_LOG_CHARS]
        if len(stripped) > JSON_PARSE_LOG_CHARS:
            snippet += "…"
        logger.warning(
            "json_parse_failed",
            label=log_label,
            source=source,
            error=str(exc),
            raw=snippet,
        )
        return JsonObjectParse(
            kind="malformed",
            error=f"Model returned malformed JSON: {exc}",
        )

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as first_exc:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if not match:
            return _fail(first_exc, source="direct")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as extract_exc:
            return _fail(extract_exc, source="extracted")

    if not isinstance(data, dict):
        logger.warning(
            "json_parse_non_object",
            label=log_label,
            type_name=type(data).__name__,
            raw=stripped[:JSON_PARSE_LOG_CHARS],
        )
        return JsonObjectParse(
            kind="not_object",
            error=f"Model returned JSON {type(data).__name__}, expected object",
        )
    return JsonObjectParse(data=data, kind="ok")
