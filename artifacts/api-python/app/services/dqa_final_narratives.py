"""AI / fallback narratives for Final DQA reports."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.domain.reporting import final_stats as _final_stats

exhaustive_executive_summary = _final_stats._exhaustive_executive_summary
pass_rate = _final_stats._pass_rate
section_prose = _final_stats._section_prose
tr1_summary = _final_stats._tr1_summary

logger = structlog.stdlib.get_logger(__name__)


def _build_final_narratives(
    stats: dict[str, Any],
    settings,
    *,
    run_ai: bool,
    system_prompt: str | None = None,
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

    from app.integrations.llm import LlmError, chat_completion, llm_config_from_app_settings

    llm = llm_config_from_app_settings(settings)
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
    from app.services.dqa_report_prompts import (
        DEFAULT_FINAL_DQA_PROMPT,
        apply_output_contract,
    )

    system = apply_output_contract("final", system_prompt or DEFAULT_FINAL_DQA_PROMPT)
    user = "Write the executive summary from this payload:\n" + json.dumps(
        compact, ensure_ascii=False
    )
    try:
        text = chat_completion(
            llm,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=float(settings.ai_temperature or 0.3),
            max_tokens=max(int(settings.ai_max_tokens or 2048), 1800),
            timeout_seconds=float(settings.ai_timeout_seconds or 90),
        )
        exec_summary = text.strip() or fallback_exec
        return {
            "aiHeadline": exec_summary,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": llm.provider,
        }
    except LlmError:
        logger.exception("final_narrative_failed")
        return {
            "aiHeadline": fallback_exec,
            "aiCoverageNote": prose["coverage"],
            "sectionProse": prose,
            "aiSource": "fallback-error",
        }


