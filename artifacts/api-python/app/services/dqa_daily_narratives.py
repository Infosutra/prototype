"""AI / fallback narratives for DQA Daily reports."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.db.models import AppSettings
from app.domain.reporting.narratives import _fallback_coverage, _fallback_headline
from app.integrations.llm import LlmError, chat_completion, llm_config_from_app_settings

logger = logging.getLogger(__name__)

def generate_ai_narratives(
    stats: dict[str, Any],
    settings: AppSettings,
    *,
    system_prompt: str | None = None,
) -> dict[str, str]:
    """Call OpenRouter with structured stats. Returns headline + coverage note."""
    if not settings.ai_enabled:
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback",
        }
    llm = llm_config_from_app_settings(settings)
    if not llm.api_key:
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
    from app.services.dqa_report_prompts import (
        DEFAULT_DAILY_DQA_PROMPT,
        apply_output_contract,
    )

    system = apply_output_contract("daily", system_prompt or DEFAULT_DAILY_DQA_PROMPT)
    user = (
        "Produce the two paragraphs from this JSON stats payload only:\n"
        + json.dumps(compact, ensure_ascii=False)
    )
    try:
        text = chat_completion(
            llm,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=int(settings.ai_max_tokens or 2048),
            timeout_seconds=float(settings.ai_timeout_seconds or 60),
        )
        parts = [p.strip() for p in text.split("\n\n") if p.strip()]
        headline = parts[0] if parts else _fallback_headline(stats)
        coverage = parts[1] if len(parts) > 1 else _fallback_coverage(stats)
        return {"aiHeadline": headline, "aiCoverageNote": coverage, "aiSource": llm.provider}
    except LlmError:
        logger.exception("OpenRouter narrative failed; using fallback")
        return {
            "aiHeadline": _fallback_headline(stats),
            "aiCoverageNote": _fallback_coverage(stats),
            "aiSource": "fallback-error",
        }
