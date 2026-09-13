"""AI insights generation (LLM call lives here — routers stay thin)."""

from __future__ import annotations

from typing import Any

from app.db.models import AppSettings
from app.integrations.llm import LlmError, chat_completion, llm_config_from_app_settings
from app.integrations.llm.json_object import parse_json_object


def generate_insight_payload(
    settings: AppSettings,
    *,
    question: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Call the LLM and return a parsed insight dict (title, summary, …)."""
    import json

    llm = llm_config_from_app_settings(settings)
    system = (
        "You are a data quality analyst for field survey data. "
        "Given study context and a user question, produce a concise insight. "
        "Respond with ONLY valid JSON using keys: "
        "title (string), summary (string), content (string), "
        "type (one of: anomaly, trend, recommendation, summary), "
        "severity (one of: critical, warning, info), "
        "tags (array of short strings). "
        "Base claims on the provided context; if evidence is thin, say so."
    )
    user = (
        f"Question:\n{question}\n\n"
        f"Context JSON:\n{json.dumps(context, default=str)[:12000]}"
    )
    try:
        raw = chat_completion(
            llm,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 800),
            timeout_seconds=float(settings.ai_timeout_seconds or 90),
        )
    except LlmError:
        raise

    parsed = parse_json_object(str(raw), log_label="AI insights").data or {}
    if not isinstance(parsed, dict):
        parsed = {}
    if not parsed:
        parsed = {"title": question[:80] or "AI Insight", "content": str(raw), "summary": ""}
    out = dict(parsed)
    out["_raw"] = raw
    return out
