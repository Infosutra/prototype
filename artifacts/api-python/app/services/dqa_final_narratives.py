"""AI / fallback narratives for Final DQA reports."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.domain.reporting.final_stats import (
    _exhaustive_executive_summary as exhaustive_executive_summary,
    _pass_rate as pass_rate,
    _section_prose as section_prose,
    _tr1_summary as tr1_summary,
)

logger = logging.getLogger(__name__)


def _build_final_narratives(
    stats: dict[str, Any], settings, *, run_ai: bool
) -> dict[str, Any]:
    prose = section_prose(stats)
    fallback_exec = exhaustive_executive_summary(stats)
    if not run_ai or not settings.ai_enabled or not (settings.ai_api_key or "").strip():
        return {
            "aiHeadline": fallback_exec,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "fallback" if run_ai else "skipped",
        }

    from app.integrations.openrouter import OpenRouterError, chat_completion

    tr1 = tr1_summary(stats)
    compact = {
        "study": stats["studyName"],
        "reportDate": stats["reportDate"],
        "totals": stats["totals"],
        "passRatePct": pass_rate(stats)[0],
        "tools": [
            {
                "tool": t["toolCode"],
                "target": t["target"],
                "actual": t["cumulative"],
                "coveragePct": t["coveragePct"],
                "red": t["redCumulative"],
                "amber": t["amberCumulative"],
                "flaggedPct": t["flaggedPct"],
            }
            for t in stats["tools"]
        ],
        "topRules": (stats.get("topRulesAll") or [])[:10],
        "findingsByTool": [
            {"tool": f["toolCode"], "summary": f["summary"], "rules": f["rules"][:3]}
            for f in (stats.get("findingsByTool") or [])
        ],
        "topEnumerators": (stats.get("enumeratorsAll") or [])[:6],
        "flagRateByDay": [
            {"day": d["dayLabel"], "flaggedPct": d["flaggedPct"]}
            for d in (stats.get("flagRateByDay") or [])
        ],
        "triangulation": {
            vid: {
                "title": p.get("title"),
                "mismatchCount": p.get("mismatchCount"),
                "rowCount": p.get("rowCount"),
            }
            for vid, p in (stats.get("triangulation") or {}).items()
        },
        "tr1ConcordancePct": tr1["concordance"],
        "tr1WidestGaps": tr1["widest"][:3],
        "draftExecutiveSummary": fallback_exec,
    }
    system = (
        "You write Final DQA close-out reports for NGO education baseline studies. "
        "This document is submitted to clients for dataset sign-off. "
        "Write an EXHAUSTIVE executive summary in 3–5 short paragraphs (blank-line separated). "
        "No markdown. Cover: (1) analysis-readiness verdict and pass rate; "
        "(2) RED/AMBER volumes, where they concentrate (tools + enumerators), leading rules; "
        "(3) whether flag rates improved across the collection window; "
        "(4) coverage vs plan by tool; "
        "(5) the main triangulation finding (TR-1 say–do concordance and widest gaps) plus TR-3/TR-5 if relevant. "
        "Stay factual; use only the JSON. Tone matches a concluding client brief."
    )
    user = "Write the executive summary from this payload:\n" + json.dumps(
        compact, ensure_ascii=False
    )
    try:
        text = chat_completion(
            api_key=settings.ai_api_key.strip(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=settings.ai_model or "nvidia/nemotron-3-super-120b-a12b:free",
            base_url=settings.ai_base_url or "https://openrouter.ai/api/v1",
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 1800),
            timeout_seconds=float(settings.ai_timeout_seconds or 90),
        )
        exec_summary = text.strip() or fallback_exec
        return {
            "aiHeadline": exec_summary,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "openrouter",
        }
    except OpenRouterError:
        logger.exception("Final DQA AI narrative failed; using exhaustive fallback")
        return {
            "aiHeadline": fallback_exec,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "fallback-error",
        }


