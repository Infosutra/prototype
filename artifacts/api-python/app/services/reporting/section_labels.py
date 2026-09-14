"""Extract and apply numbered section labels from authoring instructions."""

from __future__ import annotations

import copy
import re
from typing import Any

# Section 1.1 — Title… at line start, or "Revise the spec: Section 1.4 — …".
# Do not treat "Clarification for section 1.4: …" as a section ask.
_SECTION_ASK_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:Revise the spec:\s*)?Section\s+(\d+(?:\.\d+)?)\s*[—\-–:]\s*([^\n.]+)"
)
# remove section 1.4 / omit section 1.4 / leave section 1.4 off / drop 1.4
_SECTION_OMIT_RE = re.compile(
    r"(?i)(?:\b(?:remove|omit|drop|delete|exclude)\b(?:\s+the)?\s+section\s+"
    r"|leave(?:\s+the)?\s+section\s+|leave\s+off\s+section\s+"
    r"|omit\s+section\s+)(\d+(?:\.\d+)?)"
    r"|\b(?:remove|omit|drop|delete)\s+section\s+(\d+(?:\.\d+)?)"
    r"|Omit section\s+(\d+(?:\.\d+)?)\s+from the report"
)
_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:section\s+)?(\d+(?:\.\d+)?)\s*[—\-–:]\s*",
    re.IGNORECASE,
)
_NUMBER_IN_TEXT_RE = re.compile(
    r"(?i)(?:section\s+)?(\d+(?:\.\d+)?)\s*[—\-–]"
)


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _title_core(value: str) -> str:
    text = str(value or "").strip()
    text = _NUMBER_PREFIX_RE.sub("", text).strip()
    # Keep the short heading before the first sentence break.
    for sep in (".", ":", "\n"):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    return text


def section_number_in_text(text: str) -> str | None:
    """Best-effort section number from a question prompt or user note."""
    match = _NUMBER_IN_TEXT_RE.search(text or "")
    if match:
        return match.group(1).strip()
    match = re.search(r"(?i)\bsection\s+(\d+(?:\.\d+)?)\b", text or "")
    if match:
        return match.group(1).strip()
    return None


def extract_section_asks(instructions: str) -> list[dict[str, str]]:
    """Return active numbered section asks, honoring later remove/omit notes."""
    active, _omitted = _section_ask_state(instructions)
    return list(active.values())


def omitted_section_numbers(instructions: str) -> set[str]:
    """Section numbers the user later asked to remove/leave off."""
    _active, omitted = _section_ask_state(instructions)
    return omitted


def _section_ask_state(
    instructions: str,
) -> tuple[dict[str, dict[str, str]], set[str]]:
    events: list[tuple[int, str, str, str | None]] = []
    for match in _SECTION_ASK_RE.finditer(instructions or ""):
        number = match.group(1).strip()
        title = _title_core(match.group(2))
        if number and title:
            events.append((match.start(), "ask", number, title))
    for match in _SECTION_OMIT_RE.finditer(instructions or ""):
        number = next((g for g in match.groups() if g), None)
        if number:
            events.append((match.start(), "omit", number.strip(), None))
    for match in re.finditer(
        r"(?i)Omit section\s+(\d+(?:\.\d+)?)\s+from the report\.?",
        instructions or "",
    ):
        events.append((match.start(), "omit", match.group(1).strip(), None))

    events.sort(key=lambda row: row[0])
    active: dict[str, dict[str, str]] = {}
    omitted: set[str] = set()
    for _pos, kind, number, title in events:
        if kind == "omit":
            active.pop(number, None)
            omitted.add(number)
            continue
        omitted.discard(number)
        label = f"{number} — {title}"
        active[number] = {"number": number, "title": title or "", "label": label}
    return active, omitted


def _sections(spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    rows = spec.get("sections")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _score_match(ask_title: str, section_title: str) -> int:
    ask = _norm(_title_core(ask_title))
    have = _norm(_title_core(section_title))
    if not ask or not have:
        return 0
    if ask == have:
        return 100
    if ask in have or have in ask:
        return 80
    ask_words = {w for w in ask.split() if len(w) > 2}
    have_words = {w for w in have.split() if len(w) > 2}
    if not ask_words:
        return 0
    overlap = len(ask_words & have_words)
    if overlap == 0:
        return 0
    return int(60 * overlap / len(ask_words))


def _best_section(
    ask: dict[str, str], sections: list[dict[str, Any]], used: set[int]
) -> int | None:
    best_i: int | None = None
    best_score = 0
    for index, section in enumerate(sections):
        if index in used:
            continue
        current = str(section.get("title") or "")
        score = _score_match(ask["title"], current)
        prefix = _NUMBER_PREFIX_RE.match(current)
        if prefix and prefix.group(1) == ask["number"]:
            # Numbered title is authoritative even when wording drifted.
            score = max(score, 90)
        sid = str(section.get("id") or "").lower()
        if ask["number"].replace(".", "_") in sid or ask["number"] in sid:
            score = max(score, 70)
        if score > best_score:
            best_score = score
            best_i = index
    if best_i is None or best_score < 50:
        return None
    return best_i


def apply_section_numbers(
    spec: dict[str, Any] | None, asks: list[dict[str, str]]
) -> dict[str, Any] | None:
    """Rewrite matching section titles to include the user's numbering."""
    if not isinstance(spec, dict) or not asks:
        return spec
    out = copy.deepcopy(spec)
    sections = _sections(out)
    used: set[int] = set()
    for ask in asks:
        index = _best_section(ask, sections, used)
        if index is None:
            continue
        used.add(index)
        core = _title_core(str(sections[index].get("title") or ask["title"]))
        sections[index]["title"] = f"{ask['number']} — {core}"
    return out


def missing_section_asks(
    spec: dict[str, Any] | None, asks: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Return asks that have no matching section in the planned spec."""
    sections = _sections(spec)
    used: set[int] = set()
    missing: list[dict[str, str]] = []
    for ask in asks:
        index = _best_section(ask, sections, used)
        if index is None:
            missing.append(ask)
        else:
            used.add(index)
    return missing


def section_asks_for_missing_check(
    *,
    instructions: str,
    latest_message: str,
    clarifying_question: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Only nag about section asks in scope for this turn.

    Full prompt history still drives numbering/omits elsewhere. Re-checking every
    historical Section N.M on later turns makes old failures stick forever.
    """
    latest = extract_section_asks(latest_message or "")
    if latest:
        return latest

    if clarifying_question and str(clarifying_question.get("kind") or "") in {
        "plan_partial",
        "unmapped",
    }:
        number = section_number_in_text(str(clarifying_question.get("prompt") or ""))
        if number:
            matched = [
                ask
                for ask in extract_section_asks(instructions)
                if ask.get("number") == number
            ]
            if matched:
                return matched
            title = _title_core(str(clarifying_question.get("prompt") or ""))
            label = f"{number} — {title}" if title else f"Section {number}"
            return [
                {
                    "number": number,
                    "title": title or f"Section {number}",
                    "label": label if title else f"{number} — Section {number}",
                }
            ]
    return []


def visual_choice_from_text(text: str) -> str | None:
    """Map a clarification option/message onto a chart/table choice."""
    lower = (text or "").lower()
    if "table" in lower:
        return "table"
    if "horizontal" in lower:
        return "bar_horizontal"
    if "line" in lower:
        return "line"
    if "bar" in lower:
        return "bar"
    return None


def _chart_kind(visual: str) -> str:
    if visual == "bar":
        return "bar_horizontal"
    if visual in {"line", "bar_horizontal", "stacked_bar", "area", "pie", "donut"}:
        return visual
    return "bar_horizontal"


def wants_signoff_checklist(text: str) -> bool:
    """True when the user asked for a closing RED/AMBER sign-off checklist."""
    blob = _norm(text or "")
    if not blob:
        return False
    closing = any(
        token in blob
        for token in (
            "sign-off",
            "sign off",
            "signoff",
            "close with",
            "closing checklist",
            "read-only checklist",
            "readonly checklist",
            "read only checklist",
        )
    )
    checklist = "checklist" in blob or "sign-off" in blob or "signoff" in blob
    open_flags = any(token in blob for token in ("red", "amber", "open item", "open flag"))
    return closing and (checklist or open_flags)


def spec_has_signoff_section(spec: dict[str, Any] | None) -> bool:
    for section in _sections(spec):
        blob = _norm(f"{section.get('id') or ''} {section.get('title') or ''}")
        if "signoff" in blob or "sign-off" in blob or "sign off" in blob:
            return True
        if "checklist" in blob and any(token in blob for token in ("red", "amber", "sign")):
            return True
        comps = section.get("components") if isinstance(section.get("components"), list) else []
        for comp in comps:
            if not isinstance(comp, dict):
                continue
            cid = _norm(str(comp.get("id") or ""))
            if cid.startswith("open_red") or cid.startswith("open_amber") or "signoff" in cid:
                return True
    return False


def next_section_number(spec: dict[str, Any] | None) -> str:
    """Pick the next dotted section number from existing titled sections."""
    best_major, best_minor = 0, 0
    for section in _sections(spec):
        title = str(section.get("title") or "")
        match = _NUMBER_PREFIX_RE.match(title)
        raw = match.group(1) if match else None
        if not raw:
            sid = str(section.get("id") or "")
            sid_match = re.search(r"(\d+(?:\.\d+)?)", sid)
            raw = sid_match.group(1) if sid_match else None
        if not raw:
            continue
        parts = raw.split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            continue
        if (major, minor) > (best_major, best_minor):
            best_major, best_minor = major, minor
    if best_major == 0:
        return "1"
    return f"{best_major}.{best_minor + 1}"


def scaffold_signoff_section(
    *,
    number: str | None = None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only open RED / AMBER flag checklists for closing the report."""
    num = (number or "").strip() or next_section_number(spec)
    title = f"{num} — Sign-off checklist"
    sid = f"section_{num.replace('.', '_')}"
    columns = ["toolCode", "ruleTitle", "enumerator", "severity"]
    return {
        "id": sid,
        "title": title,
        "components": [
            {
                "id": "signoff_note",
                "type": "text",
                "display": {
                    "body": (
                        "Read-only sign-off checklist of open RED and AMBER items. "
                        "Review only — do not edit source data here."
                    )
                },
            },
            {
                "id": "open_red_items",
                "type": "table",
                "query": {
                    "entity": "flag",
                    "window": "study_to_date",
                    "filters": [{"field": "severity", "op": "eq", "value": "red"}],
                    "limit": 50,
                },
                "display": {"columns": columns},
            },
            {
                "id": "open_amber_items",
                "type": "table",
                "query": {
                    "entity": "flag",
                    "window": "study_to_date",
                    "filters": [{"field": "severity", "op": "eq", "value": "amber"}],
                    "limit": 50,
                },
                "display": {"columns": columns},
            },
        ],
    }


def scaffold_section_from_free_text(
    ask_text: str,
    *,
    spec: dict[str, Any] | None = None,
    visual: str = "table",
) -> dict[str, Any] | None:
    """Best-effort section for an unnumbered content ask (catalog-safe patterns only)."""
    blob = _norm(ask_text or "")
    if not blob:
        return None
    number = next_section_number(spec)
    if wants_signoff_checklist(ask_text):
        return scaffold_signoff_section(number=number, spec=spec)
    if _wants_enumerator_quality(blob):
        ask = {
            "number": number,
            "title": "Submission quality by enumerator",
            "label": f"{number} — Submission quality by enumerator",
        }
        return scaffold_section_for_ask(ask, visual=visual, instructions=ask_text)
    if any(
        token in blob
        for token in ("coverage", "against target", "against plan", "flag rate", "by study day")
    ):
        ask = {
            "number": number,
            "title": "Coverage and trend",
            "label": f"{number} — Coverage and trend",
        }
        return scaffold_section_for_ask(ask, visual=visual or "bar", instructions=ask_text)
    return None


def append_components_to_section(
    spec: dict[str, Any] | None,
    *,
    section_id: str,
    components: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Append components onto an existing section when the result still validates."""
    if not isinstance(spec, dict) or not section_id or not components:
        return None
    candidate = copy.deepcopy(spec)
    sections = candidate.get("sections")
    if not isinstance(sections, list):
        return None
    target = None
    for row in sections:
        if isinstance(row, dict) and str(row.get("id") or "") == section_id:
            target = row
            break
    if target is None:
        return None
    existing = target.get("components")
    if not isinstance(existing, list):
        existing = []
        target["components"] = existing
    used_ids = {
        str(comp.get("id") or "")
        for comp in existing
        if isinstance(comp, dict)
    }
    for comp in components:
        if not isinstance(comp, dict):
            continue
        row = copy.deepcopy(comp)
        cid = str(row.get("id") or "comp")
        base = cid
        n = 2
        while cid in used_ids:
            cid = f"{base}_{n}"
            n += 1
        row["id"] = cid
        used_ids.add(cid)
        existing.append(row)
    from app.domain.reporting.compile import compile_report_spec
    from app.domain.reporting.validation import validate_report_spec

    if validate_report_spec(compile_report_spec(copy.deepcopy(candidate))):
        return None
    return candidate


def spec_fingerprint(spec: dict[str, Any] | None) -> tuple[str, ...]:
    """Stable signature of section/component structure (ignore narrative prose)."""
    parts: list[str] = []
    for section in _sections(spec):
        parts.append(str(section.get("id") or ""))
        parts.append(str(section.get("title") or ""))
        comps = section.get("components") if isinstance(section.get("components"), list) else []
        for comp in comps:
            if not isinstance(comp, dict):
                continue
            parts.append(str(comp.get("id") or ""))
            parts.append(str(comp.get("type") or ""))
    return tuple(parts)


def scaffold_section_for_ask(
    ask: dict[str, str],
    *,
    visual: str,
    instructions: str = "",
) -> dict[str, Any]:
    """Build a valid counts-based section when the planner omitted a numbered ask."""
    number = str(ask.get("number") or "").strip() or "1"
    title_core = _title_core(str(ask.get("title") or "Section")) or "Section"
    title = f"{number} — {title_core}"
    sid = f"section_{number.replace('.', '_')}"
    blob = _norm(f"{title} {_section_context(ask, instructions)}")

    if _wants_enumerator_quality(blob):
        return _scaffold_enumerator_quality(
            sid=sid, title=title, number=number, visual=visual, blob=blob
        )

    wants_target = any(
        token in blob for token in ("target", "coverage", "against plan", "against target")
    )
    wants_day = any(token in blob for token in ("day", "flag rate", "trend", "moved"))

    components: list[dict[str, Any]] = []
    uses: list[str] = []

    if wants_target or not wants_day:
        cid = "submissions_vs_target"
        uses.append(cid)
        if visual == "table":
            components.append(
                {
                    "id": cid,
                    "type": "table",
                    "query": {
                        "entity": "submission",
                        "window": "study_to_date",
                        "groupBy": ["toolCode"],
                        "measures": [
                            {"id": "total", "fn": "count"},
                            {"id": "target", "fn": "sum", "field": "targetCount"},
                        ],
                    },
                    "display": {"columns": ["toolCode", "total", "target"]},
                }
            )
        else:
            kind = _chart_kind(visual)
            components.append(
                {
                    "id": cid,
                    "type": "chart",
                    "query": {
                        "entity": "submission",
                        "window": "study_to_date",
                        "groupBy": ["toolCode"],
                        "measures": [
                            {"id": "total", "fn": "count"},
                            {"id": "target", "fn": "sum", "field": "targetCount"},
                        ],
                    },
                    "display": {"kind": kind, "x": "toolCode", "y": ["total", "target"]},
                }
            )

    if wants_day or not components:
        cid = "flags_by_day"
        uses.append(cid)
        if visual == "table":
            components.append(
                {
                    "id": cid,
                    "type": "table",
                    "query": {
                        "entity": "flag",
                        "window": "study_to_date",
                        "groupBy": ["day"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"columns": ["day", "total"]},
                }
            )
        else:
            kind = _chart_kind(visual)
            components.append(
                {
                    "id": cid,
                    "type": "chart",
                    "query": {
                        "entity": "flag",
                        "window": "study_to_date",
                        "groupBy": ["day"],
                        "measures": [{"id": "total", "fn": "count"}],
                    },
                    "display": {"kind": kind, "x": "day", "y": ["total"]},
                }
            )

    components.insert(
        0,
        {
            "id": "coverage_narrative",
            "type": "narrative",
            "uses": list(uses),
            "display": {
                "role": "insight",
                "instruction": (
                    "Explain coverage against plan using submissions versus target, and how "
                    "flag volume has moved by day. Use only the counts shown — do not invent "
                    "a percentage rate."
                ),
            },
        },
    )
    return {"id": sid, "title": title, "components": components}


def _wants_enumerator_quality(blob: str) -> bool:
    has_person = any(token in blob for token in ("enumerator", "interviewer", "by enumerator"))
    has_quality = any(
        token in blob
        for token in (
            "quality",
            "clean",
            "flagged",
            "dqa issue",
            "dqa issues",
            "forms submitted",
            "submission quality",
        )
    )
    return has_person and has_quality


def wants_enumerator_quality_ask(
    ask: dict[str, str],
    *,
    instructions: str = "",
) -> bool:
    label = ask.get("label") or f"{ask.get('number')} — {ask.get('title')}"
    blob = _norm(f"{label} {_section_context(ask, instructions)}")
    return _wants_enumerator_quality(blob)


def _scaffold_enumerator_quality(
    *,
    sid: str,
    title: str,
    number: str,
    visual: str,
    blob: str,
) -> dict[str, Any]:
    """Counts by enumerator + optional DQA-issue breakdown (catalog-safe)."""
    window = "execution_date"
    if "cumulative" in blob or "study to date" in blob or "study-to-date" in blob:
        window = "study_to_date"

    quality_id = "quality_by_enumerator"
    quality_query = {
        "entity": "submission",
        "window": window,
        "groupBy": ["enumerator"],
        "measures": [
            {"id": "total", "fn": "count"},
            {"id": "clean", "fn": "countWhere", "field": "isClean", "eq": True},
            {"id": "flagged", "fn": "countWhere", "field": "isClean", "eq": False},
        ],
        "sort": {"field": "flagged", "dir": "desc"},
    }
    if visual in {"bar", "bar_horizontal", "line", "stacked_bar"} and "issue" not in blob:
        quality_comp: dict[str, Any] = {
            "id": quality_id,
            "type": "chart",
            "query": quality_query,
            "display": {
                "kind": _chart_kind(visual),
                "x": "enumerator",
                "y": ["total", "clean", "flagged"],
            },
        }
    else:
        quality_comp = {
            "id": quality_id,
            "type": "table",
            "query": quality_query,
            "display": {"columns": ["enumerator", "total", "clean", "flagged"]},
        }

    components: list[dict[str, Any]] = [quality_comp]
    if any(token in blob for token in ("issue", "dqa", "rule", "flag")):
        components.append(
            {
                "id": "dqa_issues_by_enumerator",
                "type": "table",
                "query": {
                    "entity": "flag",
                    "window": window,
                    "groupBy": ["enumerator", "ruleTitle"],
                    "measures": [{"id": "total", "fn": "count"}],
                    "sort": {"field": "total", "dir": "desc"},
                    "limit": 40,
                },
                "display": {"columns": ["enumerator", "ruleTitle", "total"]},
            }
        )
    return {"id": sid, "title": title, "components": components}


def merge_scaffolded_section(
    spec: dict[str, Any] | None, section: dict[str, Any]
) -> dict[str, Any] | None:
    """Append ``section`` when the resulting spec still validates."""
    if not isinstance(spec, dict) or not isinstance(section, dict):
        return None
    candidate = copy.deepcopy(spec)
    sections = candidate.setdefault("sections", [])
    if not isinstance(sections, list):
        return None
    # Replace same number/title if present.
    number_prefix = _NUMBER_PREFIX_RE.match(str(section.get("title") or ""))
    number = number_prefix.group(1) if number_prefix else None
    kept: list[Any] = []
    for row in sections:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "")
        prefix = _NUMBER_PREFIX_RE.match(title)
        if number and prefix and prefix.group(1) == number:
            continue
        if str(row.get("id") or "") == str(section.get("id") or ""):
            continue
        kept.append(row)
    kept.append(copy.deepcopy(section))
    candidate["sections"] = kept
    from app.domain.reporting.compile import compile_report_spec
    from app.domain.reporting.validation import validate_report_spec

    if validate_report_spec(compile_report_spec(copy.deepcopy(candidate))):
        return None
    return candidate


def missing_ask_issues(
    asks: list[dict[str, str]],
    *,
    instructions: str = "",
) -> list[dict[str, Any]]:
    """Plan-issue rows for section asks the planner dropped."""
    out: list[dict[str, Any]] = []
    for ask in asks:
        label = ask.get("label") or f"{ask.get('number')} — {ask.get('title')}"
        reason, dropped = explain_missing_section_ask(ask, instructions=instructions)
        out.append(
            {
                "section": label,
                "reason": reason,
                "path": None,
                "droppedComponent": dropped,
            }
        )
    return out


def explain_missing_section_ask(
    ask: dict[str, str],
    *,
    instructions: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """User-facing reason + faux draft component so choice buttons always appear."""
    label = ask.get("label") or f"{ask.get('number')} — {ask.get('title')}"
    blob = _norm(f"{label} {_section_context(ask, instructions)}")
    pieces = _hard_pieces(blob)
    soft = _soft_pieces(blob)
    number = ask.get("number") or "x"

    def _chart_drop(kind: str = "bar", *, x: str = "toolCode", y: list[str] | None = None) -> dict[str, Any]:
        return {
            "id": f"missing-{number}-try",
            "type": "chart",
            "display": {"kind": kind, "x": x, "y": y or ["total"]},
        }

    def _table_drop(*, columns: list[str] | None = None) -> dict[str, Any]:
        return {
            "id": f"missing-{number}-try",
            "type": "table",
            "display": {"columns": columns or ["enumerator", "total"]},
        }

    if "flag rate" in blob or "flagrate" in blob.replace(" ", ""):
        reason = (
            f"I couldn't add “{label}” yet. The study catalog can count submissions and "
            "flags (including by tool or by day) and can use target counts, but it does "
            "not have a built-in “flag rate” measure. "
        )
        if soft:
            reason += f"I can still try {soft} with plain counts, "
        else:
            reason += "I can still try daily flag counts or submissions vs target, "
        reason += (
            "show that as a bar/line chart or table, simplify the section, or leave it off."
        )
        return reason, _chart_drop("line", x="day")

    if _wants_enumerator_quality(blob):
        reason = (
            f"I couldn't add “{label}” yet. I can build enumerator quality from catalog "
            "counts: forms submitted, clean forms (`isClean`), and flagged forms by "
            "enumerator, plus a second table of exact DQA issues (enumerator × rule). "
            "I cannot invent a custom “quality score” beyond those counts. "
            "Try it as a table (best fit), a bar chart of the counts, simplify to just "
            "the enumerator summary, or leave the section off."
        )
        return reason, _table_drop(columns=["enumerator", "total", "clean", "flagged"])

    if "against target" in blob or "against plan" in blob or "coverage" in blob:
        reason = (
            f"I couldn't add “{label}” yet. Coverage / plan language is ambiguous for the "
            "builder: I can plot cumulative submissions against target by tool, and flag "
            "counts by day, but not a narrative “coverage against plan” unless you say "
            "exactly which counts to show. "
            "Rephrase with those counts, try a bar chart or table, or leave the section off."
        )
        return reason, _chart_drop("bar", x="toolCode", y=["total", "target"])

    if pieces:
        joined = ", ".join(pieces)
        reason = (
            f"I couldn't add “{label}” to the draft — especially {joined}. "
            "Say what to group by (tool, day, enumerator) and what to count, "
            "try a simpler chart or table, or leave that section off."
        )
        return reason, _chart_drop("bar")

    # Generic: still name the ask and always attach a draft so option buttons show.
    hints: list[str] = []
    if "enumerator" in blob or "interviewer" in blob:
        hints.append("group by enumerator")
    if "tool" in blob:
        hints.append("group by tool")
    if "day" in blob:
        hints.append("group by day")
    if any(token in blob for token in ("flag", "red", "amber", "dqa", "rule")):
        hints.append("count flags / rule failures")
    if any(token in blob for token in ("submission", "form", "intake")):
        hints.append("count submissions")
    hint_txt = (
        f" From your wording I would try: {', '.join(hints)}."
        if hints
        else " Say what to group by (tool, day, enumerator) and what to count."
    )
    reason = (
        f"I couldn't add “{label}” to the draft.{hint_txt} "
        "Pick a chart/table shape below, simplify that section, or leave it off."
    )
    drop = (
        _table_drop(columns=["enumerator", "total"])
        if "enumerator" in blob or "interviewer" in blob
        else _chart_drop("bar")
    )
    return reason, drop


def _section_context(ask: dict[str, str], instructions: str) -> str:
    """Pull the paragraph that introduced this section number, if present."""
    number = re.escape(str(ask.get("number") or ""))
    if not number:
        return str(ask.get("title") or "")
    match = re.search(
        rf"(?is)Section\s+{number}\s*[—\-–:]\s*(.+?)(?=\n\s*Section\s+\d|\Z)",
        instructions or "",
    )
    if match:
        return match.group(1).strip()
    return str(ask.get("title") or "")


def _hard_pieces(blob: str) -> list[str]:
    pieces: list[str] = []
    if "flag rate" in blob:
        pieces.append("flag rate")
    if "against target" in blob or "against plan" in blob:
        pieces.append("coverage against plan/target")
    if "worked example" in blob:
        pieces.append("the worked example")
    return pieces


def _soft_pieces(blob: str) -> str:
    bits: list[str] = []
    if "against target" in blob or "target" in blob:
        bits.append("cumulative submissions against target by tool")
    if "by study day" in blob or "by day" in blob or "study day" in blob:
        bits.append("flag counts by study day")
    if not bits:
        return ""
    if len(bits) == 1:
        return bits[0]
    return f"{bits[0]} and {bits[1]}"


def remove_section_by_number(
    spec: dict[str, Any] | None, number: str
) -> dict[str, Any] | None:
    """Drop sections whose title/id carries ``number`` (e.g. 1.4)."""
    if not isinstance(spec, dict) or not number:
        return spec
    out = copy.deepcopy(spec)
    kept: list[dict[str, Any]] = []
    for section in _sections(out):
        title = str(section.get("title") or "")
        sid = str(section.get("id") or "")
        prefix = _NUMBER_PREFIX_RE.match(title)
        if prefix and prefix.group(1) == number:
            continue
        if number in sid or number.replace(".", "_") in sid:
            continue
        kept.append(section)
    out["sections"] = kept
    return out
