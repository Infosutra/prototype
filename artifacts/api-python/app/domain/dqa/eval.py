"""Pure DQA check evaluation (closed operator catalog)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.dqa.context import EvaluationContext, RelatedResolution
from app.domain.dqa.refs import (
    enrich_details_with_related,
    eval_compare,
    resolve_field_value,
    resolve_numeric_operands,
    resolve_string_operands,
)
from app.domain.dqa.related import _related_submission_ref
from app.domain.dqa.values import (
    NO_VALUES,
    _any_section_filled,
    _as_list,
    _as_number,
    _as_str,
    _is_blank,
    _parse_dt,
    _threshold,
    get_value,
)

logger = logging.getLogger(__name__)

def eval_check(
    check: dict[str, Any] | None,
    *,
    data: dict[str, Any],
    pack: dict[str, Any],
    project_rows: list[Any] | None = None,
    current: Any | None = None,
    related: dict[str, RelatedResolution] | None = None,
    study_id: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (passes, details). Flag when passes is False."""
    if not check or not isinstance(check, dict):
        return True, {}
    ctx = EvaluationContext.from_eval_args(
        data=data,
        pack=pack,
        project_rows=project_rows,
        current=current,
        related=related,
        study_id=study_id,
    )
    eval_args = {
        "data": ctx.data,
        "pack": ctx.pack,
        "project_rows": ctx.project_rows,
        "current": ctx.current,
        "related": ctx.related,
        "study_id": ctx.study_id,
    }
    op = str(check.get("op") or "").strip()
    details: dict[str, Any] = {"op": op}

    if op == "all":
        for child in check.get("checks") or []:
            ok, child_details = eval_check(child, **eval_args)
            if not ok:
                return False, enrich_details_with_related(
                    {"op": op, "failed": child_details}, ctx
                )
        return True, enrich_details_with_related(details, ctx)

    if op == "any":
        for child in check.get("checks") or []:
            ok, child_details = eval_check(child, **eval_args)
            if ok:
                return True, enrich_details_with_related(details, ctx)
        return False, enrich_details_with_related(details, ctx)

    if op == "not":
        ok, child_details = eval_check(check.get("check"), **eval_args)
        return (not ok), enrich_details_with_related({"op": op, "inner": child_details}, ctx)

    if op == "if_then":
        if_ok, if_details = eval_check(check.get("if"), **eval_args)
        if not if_ok:
            return True, enrich_details_with_related(details, ctx)
        then_ok, then_details = eval_check(check.get("then"), **eval_args)
        return then_ok, enrich_details_with_related(
            {"op": op, "if": if_details, "then": then_details}, ctx
        )

    if op == "required":
        value = get_value(data, pack, check.get("field"))
        details["value"] = value
        return (not _is_blank(value)), details

    if op == "blank":
        value = get_value(data, pack, check.get("field"))
        details["value"] = value
        return _is_blank(value), details

    if op == "any_section_filled":
        prefix = str(check.get("prefix") or "")
        filled = _any_section_filled(data, prefix)
        details["prefix"] = prefix
        details["filled"] = filled
        return filled, details

    if op == "equals":
        left, right, cmp_details, na = resolve_string_operands(ctx, check)
        details.update(cmp_details)
        if cmp_details.get("error"):
            return False, enrich_details_with_related(details, ctx)
        if na is True:
            return True, enrich_details_with_related(details, ctx)
        return left == right, enrich_details_with_related(details, ctx)

    if op == "equals_any":
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        values = {_as_str(v).lower() for v in (check.get("values") or [])}
        details.update({"value": value, "expected": list(values)})
        return value in values, details

    if op == "not_equals":
        left, right, cmp_details, na = resolve_string_operands(ctx, check)
        details.update(cmp_details)
        if cmp_details.get("error"):
            return False, enrich_details_with_related(details, ctx)
        if na is True:
            return True, enrich_details_with_related(details, ctx)
        return left != right, enrich_details_with_related(details, ctx)

    if op == "in":
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        values = {_as_str(v).lower() for v in (check.get("values") or [])}
        return value in values, {"value": value, "expected": list(values)}

    if op == "not_in":
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        values = {_as_str(v).lower() for v in (check.get("values") or [])}
        return value not in values, {"value": value, "forbidden": list(values)}

    if op == "regex":
        value = _as_str(get_value(data, pack, check.get("field")))
        pattern = str(check.get("pattern") or "")
        ok = bool(re.fullmatch(pattern, value)) if pattern else False
        return ok, {"value": value, "pattern": pattern}

    if op == "min_length":
        value = _as_str(get_value(data, pack, check.get("field")))
        minimum = int(check.get("min") or 0)
        return len(value) >= minimum, {"value": value, "min": minimum, "length": len(value)}

    if op == "between":
        num = _as_number(get_value(data, pack, check.get("field")))
        lo = check.get("min")
        hi = check.get("max")
        if lo is None and check.get("min_threshold"):
            lo = _threshold(pack, str(check["min_threshold"]))
        if hi is None and check.get("max_threshold"):
            hi = _threshold(pack, str(check["max_threshold"]))
        details.update({"value": num, "min": lo, "max": hi})
        if num is None:
            return False, details
        if lo is not None and num < float(lo):
            return False, details
        if hi is not None and num > float(hi):
            return False, details
        return True, details

    if op in {"gt", "lt", "gte", "lte"}:
        left, right, cmp_details, na = resolve_numeric_operands(ctx, check)
        details.update(cmp_details)
        if cmp_details.get("error"):
            return False, enrich_details_with_related(details, ctx)
        if na is True:
            return True, enrich_details_with_related(details, ctx)
        return eval_compare(left, right, op), enrich_details_with_related(details, ctx)

    if op == "integer":
        text = _as_str(get_value(data, pack, check.get("field")))
        ok = bool(re.fullmatch(r"-?\d+", text))
        return ok, {"value": text}

    if op == "duration_minutes_gte":
        start = _parse_dt(
            resolve_field_value(ctx, check.get("start_field") or "start")
        )
        end = _parse_dt(resolve_field_value(ctx, check.get("end_field") or "end"))
        # Kobo also stores start/end as top-level meta sometimes
        if start is None:
            start = _parse_dt(data.get("start"))
        if end is None:
            end = _parse_dt(data.get("end"))
        maximum = check.get("max")
        if maximum is None and check.get("max_minutes") is not None:
            maximum = check.get("max_minutes")
        if maximum is None and check.get("max_threshold"):
            maximum = _threshold(pack, str(check["max_threshold"]))
        minimum = check.get("min")
        if minimum is None and check.get("threshold"):
            minimum = _threshold(pack, str(check["threshold"]))
        if minimum is None and maximum is None:
            minimum = _threshold(pack, "min_duration_minutes", 15)
        details.update(
            {
                "start": start.isoformat() if start else None,
                "end": end.isoformat() if end else None,
                "min": minimum,
                "max": maximum,
            }
        )
        if start is None or end is None:
            return True, details  # cannot evaluate → do not flag
        if minimum is None and maximum is None:
            return True, details
        minutes = (end - start).total_seconds() / 60.0
        details["minutes"] = minutes
        if minimum is not None and minutes < float(minimum):
            return False, details
        if maximum is not None and minutes > float(maximum):
            return False, details
        return True, details

    if op == "exclusive_choice":
        selected = set(_as_list(get_value(data, pack, check.get("field"))))
        exclusive = {_as_str(v) for v in (check.get("exclusive_values") or [])}
        details.update({"selected": list(selected), "exclusive": list(exclusive)})
        hit = selected & exclusive
        others = selected - exclusive
        # Passes when NOT (exclusive selected together with another option)
        if hit and others:
            return False, details
        return True, details

    if op == "selected_count_lte":
        selected = _as_list(get_value(data, pack, check.get("field")))
        maximum = check.get("max")
        if maximum is None and check.get("threshold"):
            maximum = _threshold(pack, str(check["threshold"]))
        details.update({"count": len(selected), "max": maximum, "selected": selected})
        if maximum is None:
            return True, details
        return len(selected) <= int(maximum), details

    if op == "skip_residue":
        parent = get_value(data, pack, check.get("parent_field"))
        parent_absent_values = {
            _as_str(v).lower() for v in (check.get("parent_absent_values") or list(NO_VALUES))
        }
        if _as_str(parent).lower() not in parent_absent_values:
            return True, details
        for child_field in check.get("child_fields") or []:
            child_val = get_value(data, pack, child_field)
            if not _is_blank(child_val):
                return False, {"parent": parent, "child_field": child_field, "child_value": child_val}
        return True, details

    if op == "all_equal":
        fields = check.get("fields") or []
        values = [_as_str(get_value(data, pack, f)) for f in fields]
        non_blank = [v for v in values if v]
        details.update({"values": values})
        if len(non_blank) < int(check.get("min_fields") or 3):
            return True, details
        return len(set(non_blank)) > 1, details  # passes when NOT all equal

    if op == "match_density_gt":
        fields = check.get("fields") or []
        match_values = {_as_str(v).lower() for v in (check.get("match_values") or [])}
        pct = check.get("pct")
        if pct is None and check.get("threshold"):
            pct = _threshold(pack, str(check["threshold"]))
        if not fields or pct is None:
            return True, details
        matched = 0
        for field in fields:
            val = _as_str(get_value(data, pack, field)).lower()
            if val in match_values:
                matched += 1
        ratio = (matched / len(fields)) * 100.0
        details.update({"matched": matched, "total": len(fields), "ratio": ratio, "pct": pct})
        # Passes when density is NOT above threshold
        return ratio <= float(pct), details

    if op == "unique_in_project":
        if not project_rows or not current:
            return True, details
        field = check.get("field")
        value = _as_str(get_value(data, pack, field))
        details["value"] = value
        if not value:
            return True, details
        related: list[dict[str, Any]] = []
        for row in project_rows:
            row_data = row.data if isinstance(row.data, dict) else {}
            other = _as_str(get_value(row_data, pack, field))
            if other == value:
                related.append(_related_submission_ref(row))
        details["count"] = len(related)
        details["relatedSubmissions"] = related
        return len(related) <= 1, details

    if op == "group_count_lte":
        if not project_rows or not current:
            return True, details
        field = check.get("field")
        value = _as_str(get_value(data, pack, field))
        maximum = check.get("max")
        if maximum is None and check.get("threshold"):
            maximum = _threshold(pack, str(check["threshold"]))
        if not value or maximum is None:
            return True, details
        related: list[dict[str, Any]] = []
        for row in project_rows:
            row_data = row.data if isinstance(row.data, dict) else {}
            if _as_str(get_value(row_data, pack, field)) == value:
                related.append(_related_submission_ref(row))
        details.update(
            {
                "value": value,
                "count": len(related),
                "max": maximum,
                "relatedSubmissions": related,
            }
        )
        return len(related) <= int(maximum), details

    if op == "gps_present":
        geo = data.get("_geolocation")
        loc = current.location if current else None
        present = False
        if isinstance(geo, list) and len(geo) >= 2 and geo[0] is not None and geo[1] is not None:
            present = True
        if loc:
            present = True
        details["present"] = present
        return present, details

    if op == "attachment_count_gte":
        minimum = int(check.get("min") or 1)
        count = current.attachment_count if current else 0
        attachments = data.get("_attachments")
        if isinstance(attachments, list):
            count = max(count, len(attachments))
        details.update({"count": count, "min": minimum})
        return count >= minimum, details

    if op == "specify_valid":
        trigger_field = check.get("trigger_field")
        trigger_values = {_as_str(v).lower() for v in (check.get("trigger_values") or [])}
        text_field = check.get("text_field")
        min_len = int(check.get("min_length") or 3)
        junk = {_as_str(v).lower() for v in (check.get("junk_values") or ["na", "n/a", "xx", "-", "."])}
        trigger = _as_str(get_value(data, pack, trigger_field)).lower()
        selected = set(_as_list(get_value(data, pack, trigger_field)))
        triggered = trigger in trigger_values or bool(selected & {_as_str(v) for v in (check.get("trigger_values") or [])})
        if not triggered:
            return True, details
        text = _as_str(get_value(data, pack, text_field))
        details.update({"text": text, "trigger": trigger})
        if len(text) < min_len or text.lower() in junk:
            return False, details
        return True, details

    logger.warning("Unknown DQA operator: %s", op)
    return True, enrich_details_with_related(details, ctx)
