"""Turn ReportSpec validation failures into plain-language authoring prompts."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

_SECTION_RE = re.compile(r"sections\.(\d+)")
_COMPONENT_RE = re.compile(r"components\.(\d+)")

DEFAULT_EXPLAIN_PROMPT = """You help a field researcher author a report template in chat.
Rewrite a technical validation problem into ONE short clarification.

The user must understand WHICH part of THEIR request failed — quote or paraphrase that
slice of userInstructions (e.g. "flag rate by study day", "cumulative submissions against
target by tool"). Do NOT invent a chart type the user did not ask for.

Rules:
- 2–4 sentences. Calm and concrete.
- First sentence: name the exact ask from userInstructions that we could not include.
- Second: one plain reason grounded in technicalError (unknown field, unsupported measure
  like rate/ratio, missing binding, etc.). Never say "a specific condition was not met".
- If the failed draft used a chart kind, you may mention it as what we tried — but the
  failed ask is still the user's wording.
- End with choices: keep the rest / rephrase / try another chart or table / leave off.
- Never mention JSON, schemas, Pydantic, "extra inputs", validation paths, or property names
  like orientation/stacked/seriesField.
- If suspectedUserAsk is provided, treat it as the failing piece unless clearly wrong.
- Return JSON only: {"prompt": "...", "failedAsk": "..."}.
"""


class ExplainInvoker(Protocol):
    def __call__(
        self,
        *,
        system: str,
        user: str,
        purpose: str,
    ) -> dict[str, Any]: ...


_CHART_KIND_LABELS = {
    "bar": "bar chart",
    "bar_horizontal": "horizontal bar chart",
    "stacked_bar": "stacked bar chart",
    "line": "line chart",
    "area": "area chart",
    "pie": "pie chart",
    "donut": "donut chart",
}

def _section_title(spec: dict[str, Any] | None, index: int) -> str | None:
    if not isinstance(spec, dict):
        return None
    sections = spec.get("sections")
    if not isinstance(sections, list) or index < 0 or index >= len(sections):
        return None
    section = sections[index]
    if not isinstance(section, dict):
        return None
    title = str(section.get("title") or "").strip()
    return title or None


def _section_snippet(spec: dict[str, Any] | None, index: int) -> dict[str, Any] | None:
    if not isinstance(spec, dict):
        return None
    sections = spec.get("sections")
    if not isinstance(sections, list) or index < 0 or index >= len(sections):
        return None
    section = sections[index]
    return section if isinstance(section, dict) else None


def _where(error: str, spec: dict[str, Any] | None) -> str:
    match = _SECTION_RE.search(error)
    if not match:
        return "this part of the report"
    index = int(match.group(1))
    title = _section_title(spec, index)
    if title:
        return f'“{title}”'
    return f"section {index + 1}"


def _extra_input_key(error: str) -> str | None:
    text = (error or "").strip()
    if "extra inputs are not permitted" not in text.lower():
        return None
    left, _, _right = text.partition(":")
    parts = [p for p in left.split(".") if p and not p.isdigit()]
    if parts:
        return parts[-1]
    return None


def _component_index(error: str) -> int | None:
    match = _COMPONENT_RE.search(error or "")
    if not match:
        return None
    return int(match.group(1))


def _component_at(section: dict[str, Any] | None, index: int | None) -> dict[str, Any] | None:
    if section is None or index is None:
        return None
    components = section.get("components")
    if not isinstance(components, list) or index < 0 or index >= len(components):
        return None
    row = components[index]
    return row if isinstance(row, dict) else None


def describe_component(component: dict[str, Any] | None) -> str | None:
    """Plain label for a failed component draft."""
    if not isinstance(component, dict):
        return None
    ctype = str(component.get("type") or "").strip()
    display = component.get("display") if isinstance(component.get("display"), dict) else {}
    kind = str(display.get("kind") or "").strip()
    if ctype == "chart":
        label = _CHART_KIND_LABELS.get(kind)
        if label:
            return f"the {label}"
        return "the chart"
    if ctype == "table":
        return "the table"
    if ctype == "kpi_group":
        return "the KPI cards"
    if ctype == "narrative":
        return "the written summary"
    if ctype == "metric":
        return "the metric"
    if ctype == "progress":
        return "the progress bars"
    return f"the {ctype}" if ctype else None


def guess_failed_ask(
    *,
    instructions: str,
    forbidden_key: str | None = None,
    component: dict[str, Any] | None = None,
    technical: str = "",
) -> str | None:
    """Map error context onto a concrete slice of the user's English request."""
    text = instructions or ""
    lower = text.lower()
    comp_label = describe_component(component)
    display = component.get("display") if isinstance(component, dict) else {}
    kind = str((display or {}).get("kind") or "").lower()
    key = (forbidden_key or "").lower()
    tech = (technical or "").lower()

    candidates: list[tuple[int, str]] = []

    def add(score: int, phrase: str) -> None:
        if phrase:
            candidates.append((score, phrase))

    # Prefer the user's wording for 1.4-style coverage/trend asks.
    if "flag rate" in lower and ("study day" in lower or "by day" in lower or "by study" in lower):
        add(96, "flag rate by study day")
    elif "cumulative flag rate" in lower:
        add(90, "the cumulative flag rate trend")
    elif "flag rate" in lower:
        add(85, "the flag rate")
    if "against target" in lower or "against plan" in lower:
        add(92, "cumulative submissions against target by tool")
    if "coverage against" in lower or ("coverage" in lower and "trend" in lower):
        add(70, "coverage and trend")

    # Chart kinds from the failed component draft — lower score if user never named them.
    if kind == "stacked_bar" or key == "stacked" or (display or {}).get("stacked") is True:
        if "stacked" in lower:
            add(90, "the stacked bar chart of RED and AMBER by tool")
        else:
            add(55, "the stacked bar chart")
    if kind == "bar_horizontal" or key == "orientation":
        if "rules failing" in lower or "failing most" in lower:
            add(95, "the horizontal bar chart of rules failing most often today")
        elif "horizontal" in lower:
            add(85, "the horizontal bar chart")
        else:
            add(50, "the horizontal bar chart")
    if kind == "line":
        if "line" in lower:
            add(88, "the line chart")
        else:
            add(30, "the trend chart")

    # Phrases from the user request that often fail.
    if "percentage" in lower or "percent" in lower:
        add(75 if "flagged" in lower else 60, "the percentage of today's submissions flagged")
    if "median" in lower or "median" in tech:
        add(90, "median interview time")
    if "worked example" in lower:
        add(85, "the worked example for finding records in KoboToolbox")

    if key in {"orientation", "stacked", "series", "seriesfield", "caption"} and comp_label:
        add(65, comp_label)
    if comp_label and not candidates:
        add(40, comp_label)

    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1]


def explain_validation_error(
    error: str,
    *,
    spec: dict[str, Any] | None = None,
    instructions: str = "",
    section_draft: dict[str, Any] | None = None,
    dropped_component: dict[str, Any] | None = None,
) -> str:
    """One user-facing clarification (heuristic fallback)."""
    text = (error or "").strip()
    lower = text.lower()
    where = _where(text, spec)
    section = section_draft
    if section is None:
        match = _SECTION_RE.search(text)
        if match:
            section = _section_snippet(spec, int(match.group(1)))
    component = dropped_component or _component_at(section, _component_index(text))
    failed_ask = guess_failed_ask(
        instructions=instructions,
        forbidden_key=_extra_input_key(text),
        component=component,
        technical=text,
    )
    ask = failed_ask or describe_component(component)
    tried = describe_component(component) if str((component or {}).get("type") or "") == "chart" else None

    if "narrative requires query or uses" in lower:
        target = ask or "the written summary"
        return (
            f"I couldn't include {target} in {where}: it needs to draw from an earlier "
            "table or chart. Tell me which one to summarize, or leave that paragraph off."
        )
    if "extra inputs are not permitted" in lower or "extra_forbidden" in lower:
        if ask:
            return (
                f"I couldn't include {ask} in {where} — that option isn't supported in "
                "this builder yet. I can keep the rest of the section; rephrase that piece, "
                "or say to leave it off."
            )
        return (
            f"In {where}, one chart or table option isn't supported yet. "
            "Which block should I drop, or how should I rephrase it?"
        )
    if "text components must not" in lower:
        return (
            f"For {where}, static text and data queries got mixed together. "
            "Should that block be plain wording only, or a data-backed chart/table?"
        )
    if "kpi_group" in lower and "requires" in lower:
        return (
            f"For {where}, the KPI cards are missing clear measures. "
            "Which counts should appear on those cards?"
        )
    if "requires a query" in lower or "requires query" in lower:
        target = ask or "that block"
        return (
            f"I couldn't bind {target} in {where} to a data query. "
            "Rephrase what to count or show, or leave that block off."
        )
    if "median" in lower:
        return (
            f"I couldn't include median interview time in {where} — median isn't available yet. "
            "Use average interview time instead, or omit duration?"
        )
    if (
        "unknown fn" in lower
        or "input should be 'count'" in lower
        or (
            ("measure" in lower or " fn " in f" {lower} " or "fn '" in lower or ".fn:" in lower)
            and ("rate" in lower or "ratio" in lower)
        )
    ):
        target = ask or "that measure"
        tried_bit = f" (I tried {tried})" if tried else ""
        return (
            f"I couldn't include {target} in {where}{tried_bit}: the catalog can count "
            "rows and filter by severity, but it does not have a built-in rate/ratio measure. "
            "I can show daily flag counts as a bar or line chart, a table, or leave that piece off."
        )
    if "unknown" in lower and ("field" in lower or "id" in lower or "fn" in lower):
        target = ask or "that block"
        tried_bit = f" I tried {tried}." if tried else ""
        return (
            f"I couldn't include {target} in {where}.{tried_bit} "
            "A name did not match the study catalog. Pick another chart shape, "
            "show it as a table, rephrase the measure, or leave that piece off."
        )
    if "duplicate component id" in lower:
        return (
            f"For {where}, two blocks collided. "
            "Restate that section briefly and I'll rebuild it."
        )
    if "max is" in lower and "section" in lower:
        return (
            "The report is getting too large for one pass. "
            "Add the next sections one at a time."
        )
    if "failed validation" in lower:
        _, _, rest = text.partition(": ")
        if rest and rest != text:
            parts = [p.strip() for p in rest.split(";") if p.strip()]
            if parts:
                return explain_validation_error(
                    parts[0],
                    spec=spec,
                    instructions=instructions,
                    section_draft=section_draft,
                    dropped_component=dropped_component,
                )
        return (
            "I could not finish mapping that last request into a valid report. "
            "Try sending the next section on its own, or tell me which part to skip."
        )

    if ask:
        tried_bit = f" I tried {tried}." if tried and tried not in ask else ""
        return (
            f"I couldn't include {ask} in {where}.{tried_bit} "
            "Rephrase that piece, try another chart or a table, or say to leave it off — "
            "I'll keep the rest."
        )
    return (
        f"For {where}, I could not finish mapping that request cleanly. "
        "Can you rephrase what you want there, or say to leave it off?"
    )


def explain_validation_errors(
    errors: list[str],
    *,
    spec: dict[str, Any] | None = None,
    instructions: str = "",
    limit: int = 4,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in errors or []:
        message = explain_validation_error(str(raw), spec=spec, instructions=instructions)
        if message in seen:
            continue
        seen.add(message)
        out.append(message)
        if len(out) >= limit:
            break
    return out


def _llm_rewrite_prompt(
    *,
    technical: str,
    fallback: str,
    instructions: str,
    section_title: str | None,
    section_snippet: dict[str, Any] | None,
    forbidden_key: str | None,
    dropped_component: dict[str, Any] | None,
    suspected_ask: str | None,
    invoker: ExplainInvoker,
) -> str:
    payload = {
        "userInstructions": instructions,
        "sectionTitle": section_title,
        "technicalError": technical,
        "forbiddenProperty": forbidden_key,
        "failedComponent": dropped_component,
        "failedComponentLabel": describe_component(dropped_component),
        "suspectedUserAsk": suspected_ask,
        "sectionDraft": section_snippet,
        "fallbackPrompt": fallback,
    }
    try:
        raw = invoker(
            system=DEFAULT_EXPLAIN_PROMPT,
            user=json.dumps(payload, default=str),
            purpose="explain",
        )
    except Exception:  # noqa: BLE001
        return fallback
    if not isinstance(raw, dict):
        return fallback
    prompt = str(raw.get("prompt") or raw.get("message") or "").strip()
    if not prompt or len(prompt) < 20:
        return fallback
    lower = prompt.lower()
    if any(
        bad in lower
        for bad in ("extra inputs", "pydantic", "json schema", "specversion", "components.0")
    ):
        return fallback
    # If the model stayed vague, prefer the heuristic that names the ask.
    if "specific condition" in lower or "specific data query" in lower:
        return fallback
    vague = (
        "that part of the report" in lower
        or ("rephrase it" in lower and suspected_ask and suspected_ask.lower() not in lower)
    )
    if vague and suspected_ask and suspected_ask.lower() not in lower:
        return fallback
    # Don't let the rewrite invent a chart type the user never named.
    if (
        suspected_ask
        and "line chart" in lower
        and "line" not in (instructions or "").lower()
        and "line" not in suspected_ask.lower()
    ):
        return fallback
    return prompt


def humanize_validation_error(
    error: str,
    *,
    spec: dict[str, Any] | None = None,
    instructions: str = "",
    invoker: ExplainInvoker | None = None,
    section_draft: dict[str, Any] | None = None,
    dropped_component: dict[str, Any] | None = None,
) -> str:
    """Heuristic explanation, optionally rewritten by the LLM for clarity."""
    match = _SECTION_RE.search(error or "")
    index = int(match.group(1)) if match else -1
    section = section_draft or (_section_snippet(spec, index) if index >= 0 else None)
    component = dropped_component or _component_at(section, _component_index(error))
    fallback = explain_validation_error(
        error,
        spec=spec,
        instructions=instructions,
        section_draft=section,
        dropped_component=component,
    )
    if invoker is None:
        return fallback
    suspected = guess_failed_ask(
        instructions=instructions,
        forbidden_key=_extra_input_key(error),
        component=component,
        technical=error,
    )
    return _llm_rewrite_prompt(
        technical=error,
        fallback=fallback,
        instructions=instructions,
        section_title=_section_title(spec, index) if index >= 0 else (
            str(section.get("title")) if isinstance(section, dict) else None
        ),
        section_snippet=section,
        forbidden_key=_extra_input_key(error),
        dropped_component=component,
        suspected_ask=suspected,
        invoker=invoker,
    )


def humanize_plan_issues(
    issues: list[dict[str, Any]],
    *,
    instructions: str = "",
    spec: dict[str, Any] | None = None,
    invoker: ExplainInvoker | None = None,
) -> list[dict[str, Any]]:
    """Rewrite salvage/partial issue reasons for the chat UI."""
    out: list[dict[str, Any]] = []
    for item in issues or []:
        if not isinstance(item, dict):
            continue
        section = str(item.get("section") or "").strip()
        reason = str(item.get("reason") or "").strip()
        technical = str(item.get("technical") or reason)
        section_draft = (
            item.get("sectionDraft") if isinstance(item.get("sectionDraft"), dict) else None
        )
        dropped = (
            item.get("droppedComponent")
            if isinstance(item.get("droppedComponent"), dict)
            else None
        )
        prompt = humanize_validation_error(
            technical or reason,
            spec=spec,
            instructions=instructions,
            invoker=invoker,
            section_draft=section_draft,
            dropped_component=dropped,
        )
        # If heuristic already named the ask, keep section title context when useful.
        if section and section.lower() not in prompt.lower() and "“" not in prompt:
            prompt = f"In “{section}”: {prompt}"
        out.append({**item, "reason": prompt})
    return out


def partial_issue_question(
    prompt: str,
    *,
    index: int = 0,
    dropped_component: dict[str, Any] | None = None,
) -> dict[str, Any]:
    options: list[dict[str, str]] = []
    ctype = str((dropped_component or {}).get("type") or "")
    display = (
        dropped_component.get("display")
        if isinstance(dropped_component, dict)
        and isinstance(dropped_component.get("display"), dict)
        else {}
    )
    tried_kind = str(display.get("kind") or "").strip()
    # Always offer shape choices for missing/partial sections (even when no draft).
    if ctype in {"", "chart", "table"}:
        chart_choices = [
            ("bar", "Try as a bar chart", "use a bar chart for that piece"),
            ("line", "Try as a line chart", "use a line chart for that piece"),
            (
                "bar_horizontal",
                "Try as a horizontal bar",
                "use a horizontal bar chart for that piece",
            ),
            ("table", "Show it as a table", "show that piece as a table instead"),
        ]
        for kind, label, value in chart_choices:
            if kind == "table" or kind != tried_kind:
                options.append({"id": f"as_{kind}", "label": label, "value": value})
    options.extend(
        [
            {"id": "retry", "label": "I'll clarify", "value": "clarify"},
            {"id": "skip", "label": "Leave that part off", "value": "skip"},
        ]
    )
    return {
        "id": f"plan-partial:{index}",
        "kind": "plan_partial",
        "prompt": prompt,
        "options": options,
    }
