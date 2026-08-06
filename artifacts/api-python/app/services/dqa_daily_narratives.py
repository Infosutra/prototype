"""AI / fallback narratives for DQA Daily reports."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db.models import AppSettings
from app.domain.reporting.narratives import _fallback_coverage, _fallback_headline
from app.integrations.openrouter import OpenRouterError, chat_completion

logger = logging.getLogger(__name__)

def generate_ai_narratives(stats: dict[str, Any], settings: AppSettings) -> dict[str, str]:
    """Call OpenRouter with structured stats. Returns headline + coverage note."""
    if not settings.ai_enabled:
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback",
        }
    api_key = (settings.ai_api_key or "").strip()
    if not api_key:
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback-no-key",
        }

    compact = {
        "study": stats["studyName"],
        "dayNumber": stats["dayNumber"],
        "reportDate": stats["reportDate"],
        "totals": stats["totals"],
        "tools": [
            {
                "tool": t["toolCode"],
                "newToday": t["newToday"],
                "cumulative": t["cumulative"],
                "target": t["target"],
                "coveragePct": t["coveragePct"],
                "redToday": t["redToday"],
                "amberToday": t["amberToday"],
                "flaggedPctToday": t["flaggedPctToday"],
            }
            for t in stats["tools"]
        ],
        "topRulesToday": stats["topRulesToday"][:8],
        "redGrouped": (stats.get("redGrouped") or [])[:8],
        "enumeratorWatch": stats["enumerators"][:5],
        "flagRateByDay": (stats.get("flagRateByDay") or [])[-5:],
    }
    system = (
        "You are a field data quality analyst for an NGO education baseline study. "
        "Write concise, factual prose for a daily DQA email used to drive same-day back-checks. "
        "No markdown. No speculation beyond the numbers. "
        "Respond with exactly two paragraphs separated by a blank line: "
        "(1) Today's headline — 1–3 sentences naming new submissions, RED count to back-check tomorrow, "
        "and the leading AMBER theme by tool; "
        "(2) Coverage & trend — coverage vs plan (call out any lagging tool), how the cumulative flag rate "
        "has moved across study days, and the concrete action for tomorrow."
    )
    user = (
        "Produce the two paragraphs from this JSON stats payload only:\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    try:
        text = chat_completion(
            api_key=api_key,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=settings.ai_model or "nvidia/nemotron-3-super-120b-a12b:free",
            base_url=settings.ai_base_url or "https://openrouter.ai/api/v1",
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=int(settings.ai_max_tokens or 2048),
            timeout_seconds=float(settings.ai_timeout_seconds or 60),
        )
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        headline = parts[0] if parts else _fallback_headline(stats)
        coverage = parts[1] if len(parts) > 1 else _fallback_coverage(stats)
        return {"aiHeadline": headline, "aiCoverageNote": coverage, "aiSource": "openrouter"}
    except OpenRouterError:
        logger.exception("OpenRouter narrative failed; using fallback")
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback-error",
        }
