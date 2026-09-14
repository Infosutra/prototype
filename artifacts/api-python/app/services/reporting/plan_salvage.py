"""Keep as much of a planned ReportSpec as validates when the full draft fails."""

from __future__ import annotations

import copy
from typing import Any

from app.domain.reporting.compile import compile_report_spec
from app.domain.reporting.validation import validate_report_spec
from app.services.reporting.plan_explain import explain_validation_error


def _shell(spec: dict[str, Any] | None) -> dict[str, Any]:
    source = spec if isinstance(spec, dict) else {}
    return {
        "specVersion": str(source.get("specVersion") or source.get("spec_version") or "1.0"),
        "title": str(source.get("title") or "Untitled report"),
        "sections": [],
        **(
            {"subtitle": source["subtitle"]}
            if isinstance(source.get("subtitle"), str) and source.get("subtitle")
            else {}
        ),
    }


def _sections(spec: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(spec, dict):
        return []
    rows = spec.get("sections")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_title(value: Any) -> str:
    return " ".join(str(value or "").lower().split())


def _section_keys(section: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    sid = str(section.get("id") or "").strip().lower()
    if sid:
        keys.add(f"id:{sid}")
    title = _normalize_title(section.get("title"))
    if title:
        keys.add(f"title:{title}")
    return keys


def _is_valid(spec: dict[str, Any]) -> bool:
    return validate_report_spec(compile_report_spec(copy.deepcopy(spec))) == []


_CHART_KIND_FALLBACKS: tuple[str, ...] = (
    "bar",
    "line",
    "bar_horizontal",
    "stacked_bar",
    "area",
)


def _with_chart_kind(component: dict[str, Any], kind: str) -> dict[str, Any]:
    out = copy.deepcopy(component)
    display = out.get("display")
    if not isinstance(display, dict):
        display = {}
        out["display"] = display
    display["kind"] = kind
    return out


def _chart_kind_attempts(component: dict[str, Any]) -> list[dict[str, Any]]:
    """Original chart, then alternate kinds (same query/axes)."""
    if str(component.get("type") or "") != "chart":
        return [copy.deepcopy(component)]
    display = component.get("display") if isinstance(component.get("display"), dict) else {}
    original = str(display.get("kind") or "bar").strip() or "bar"
    kinds: list[str] = []
    for kind in (original, *_CHART_KIND_FALLBACKS):
        if kind not in kinds:
            kinds.append(kind)
    return [_with_chart_kind(component, kind) for kind in kinds]


def autofix_narratives(spec: dict[str, Any]) -> dict[str, Any]:
    """Attach ``uses`` to narratives that forgot to reference earlier components."""
    out = copy.deepcopy(spec)
    prior_ids: list[str] = []
    for section in _sections(out):
        components = section.get("components")
        if not isinstance(components, list):
            continue
        section_ids: list[str] = []
        for component in components:
            if not isinstance(component, dict):
                continue
            cid = str(component.get("id") or "").strip()
            if component.get("type") == "narrative":
                has_query = isinstance(component.get("query"), dict) and bool(
                    component.get("query")
                )
                uses = component.get("uses")
                has_uses = isinstance(uses, list) and any(str(x).strip() for x in uses)
                if not has_query and not has_uses:
                    refs = section_ids or prior_ids[-6:]
                    if refs:
                        component["uses"] = list(refs)
            if cid:
                section_ids.append(cid)
                prior_ids.append(cid)
    return out


def _try_with_section(
    base: dict[str, Any], section: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any] | None]:
    """Add a whole section, or fall back to component-by-component.

    Returns ``(spec_or_none, errors, last_dropped_component)``.
    """
    candidate = copy.deepcopy(base)
    candidate.setdefault("sections", []).append(copy.deepcopy(section))
    if _is_valid(candidate):
        return candidate, [], None

    components = section.get("components")
    if not isinstance(components, list) or not components:
        errors = validate_report_spec(compile_report_spec(copy.deepcopy(candidate)))
        return None, errors, None

    partial_section = {
        key: value for key, value in section.items() if key != "components"
    }
    partial_section["components"] = []
    working = copy.deepcopy(base)
    accepted = False
    dropped_errors: list[str] = []
    last_dropped: dict[str, Any] | None = None
    for component in components:
        if not isinstance(component, dict):
            continue
        kept = False
        attempt_errors: list[str] = []
        for attempt in _chart_kind_attempts(component):
            trial_section = copy.deepcopy(partial_section)
            trial_section["components"] = list(partial_section["components"]) + [
                copy.deepcopy(attempt)
            ]
            trial = copy.deepcopy(working)
            if partial_section["components"]:
                trial["sections"] = list(working.get("sections") or [])[:-1] + [
                    trial_section
                ]
            else:
                trial["sections"] = list(working.get("sections") or []) + [trial_section]
            if _is_valid(trial):
                working = trial
                partial_section = trial_section
                accepted = True
                kept = True
                break
            attempt_errors = validate_report_spec(
                compile_report_spec(copy.deepcopy(trial))
            )
        if not kept:
            last_dropped = copy.deepcopy(component)
            if attempt_errors:
                dropped_errors.extend(attempt_errors)
            else:
                trial_section = copy.deepcopy(partial_section)
                trial_section["components"] = list(partial_section["components"]) + [
                    copy.deepcopy(component)
                ]
                trial = copy.deepcopy(working)
                if partial_section["components"]:
                    trial["sections"] = list(working.get("sections") or [])[:-1] + [
                        trial_section
                    ]
                else:
                    trial["sections"] = list(working.get("sections") or []) + [
                        trial_section
                    ]
                dropped_errors.extend(
                    validate_report_spec(compile_report_spec(copy.deepcopy(trial)))
                )

    if accepted and _is_valid(working):
        return working, dropped_errors, last_dropped
    return (
        None,
        dropped_errors
        or validate_report_spec(compile_report_spec(copy.deepcopy(candidate))),
        last_dropped,
    )


def _issue(
    *,
    title: str,
    tech: str,
    section: dict[str, Any],
    dropped: dict[str, Any] | None,
    kept_partial: bool = False,
) -> dict[str, Any]:
    reason = explain_validation_error(
        tech,
        spec={"sections": [section]},
        section_draft=section,
        dropped_component=dropped,
    )
    if kept_partial:
        reason = f"I kept part of “{title}”, but skipped a block inside it. {reason}"
    return {
        "section": title,
        "reason": reason,
        "technical": tech,
        "sectionDraft": copy.deepcopy(section),
        "droppedComponent": copy.deepcopy(dropped) if dropped else None,
    }


def _build_incremental(candidate: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    working = _shell(candidate)
    issues: list[dict[str, str]] = []
    for section in _sections(candidate):
        title = str(section.get("title") or section.get("id") or "Untitled section")
        nxt, errors, dropped = _try_with_section(working, section)
        if nxt is None:
            tech = errors[0] if errors else "invalid section"
            issues.append(_issue(title=title, tech=tech, section=section, dropped=dropped))
            continue
        if errors:
            tech = errors[0]
            issues.append(
                _issue(
                    title=title,
                    tech=tech,
                    section=section,
                    dropped=dropped,
                    kept_partial=True,
                )
            )
        working = nxt
    if not _sections(working):
        return None, issues
    return working, issues


def _build_from_baseline(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not _is_valid(baseline):
        return None, []
    working = copy.deepcopy(baseline)
    existing: set[str] = set()
    for section in _sections(working):
        existing |= _section_keys(section)
    issues: list[dict[str, str]] = []
    for section in _sections(candidate):
        keys = _section_keys(section)
        if keys & existing:
            continue
        title = str(section.get("title") or section.get("id") or "Untitled section")
        nxt, errors, dropped = _try_with_section(working, section)
        if nxt is None:
            tech = errors[0] if errors else "invalid section"
            issues.append(_issue(title=title, tech=tech, section=section, dropped=dropped))
            continue
        if errors:
            tech = errors[0]
            issues.append(
                _issue(
                    title=title,
                    tech=tech,
                    section=section,
                    dropped=dropped,
                    kept_partial=True,
                )
            )
        working = nxt
        existing |= keys
    return working, issues


def _score(spec: dict[str, Any] | None) -> tuple[int, int]:
    if not spec:
        return (0, 0)
    sections = _sections(spec)
    components = 0
    for section in sections:
        comps = section.get("components")
        if isinstance(comps, list):
            components += len(comps)
    return (len(sections), components)


def salvage_report_spec(
    candidate: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Return a valid subset of ``candidate``, preferring to keep ``baseline``.

    Result shape::
        {
          "spec": dict | None,
          "issues": [{"section", "reason"}, ...],
          "keptFrom": "candidate" | "baseline" | "baseline+new" | "none",
        }
    """
    fixed = autofix_narratives(candidate if isinstance(candidate, dict) else {})
    if _is_valid(fixed):
        return {"spec": compile_report_spec(fixed), "issues": [], "keptFrom": "candidate"}

    options: list[tuple[str, dict[str, Any] | None, list[dict[str, str]]]] = []

    incr, incr_issues = _build_incremental(fixed)
    options.append(("candidate", incr, incr_issues))

    if isinstance(baseline, dict) and baseline:
        base_fixed = autofix_narratives(baseline)
        if _is_valid(base_fixed):
            merged, merged_issues = _build_from_baseline(base_fixed, fixed)
            options.append(("baseline+new", merged, merged_issues))
            options.append(("baseline", copy.deepcopy(base_fixed), []))

    best_name = "none"
    best_spec: dict[str, Any] | None = None
    best_issues: list[dict[str, str]] = []
    best_score = (-1, -1)
    for name, spec, issues in options:
        if spec is None or not _is_valid(spec):
            continue
        score = _score(spec)
        # Prefer more content; when tied, prefer baseline+new then baseline.
        rank = {"baseline+new": 2, "baseline": 1, "candidate": 0}.get(name, 0)
        if score > best_score or (score == best_score and rank > {"baseline+new": 2, "baseline": 1, "candidate": 0}.get(best_name, -1)):
            best_score = score
            best_name = name
            best_spec = compile_report_spec(spec)
            best_issues = issues

    if best_spec is None:
        fallback_issues = best_issues
        if not fallback_issues and errors:
            tech = errors[0]
            fallback_issues = [
                {
                    "section": "request",
                    "reason": explain_validation_error(tech, spec=candidate),
                    "technical": tech,
                }
            ]
        return {"spec": None, "issues": fallback_issues, "keptFrom": "none"}

    # If we only kept the baseline, surface why new parts were dropped.
    if best_name == "baseline" and not best_issues:
        for name, _spec, issues in options:
            if name == "baseline+new" and issues:
                best_issues = issues
                break
        if not best_issues and errors:
            tech = errors[0]
            best_issues = [
                {
                    "section": "new request",
                    "reason": explain_validation_error(tech, spec=candidate),
                    "technical": tech,
                }
            ]

    return {"spec": best_spec, "issues": best_issues, "keptFrom": best_name}
