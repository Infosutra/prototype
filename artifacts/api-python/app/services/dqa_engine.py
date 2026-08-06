"""Declarative DQA rule engine.

Rule packs map logical field aliases to Kobo leaf names and define checks
using a closed operator catalog. Evaluation writes rows to ``dqa_flags``.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import DqaFlag, Project, RulePack, Submission

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "rule_packs"

YES_VALUES = {"1", "yes", "y", "true"}
NO_VALUES = {"2", "0", "no", "n", "false"}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def find_field_value(data: dict[str, Any], field_name: str | None) -> Any:
    if not field_name:
        return None
    if field_name in data:
        return data[field_name]
    suffix = f"/{field_name}"
    for key, value in data.items():
        if key.endswith(suffix):
            return value
    return None


def resolve_alias(pack: dict[str, Any], alias: str) -> str | None:
    fields = pack.get("fields") or {}
    if alias in fields:
        return str(fields[alias])
    return alias


def get_value(data: dict[str, Any], pack: dict[str, Any], field_ref: str | None) -> Any:
    if not field_ref:
        return None
    # Prefer alias resolution; fall back to treating field_ref as leaf name.
    leaf = resolve_alias(pack, field_ref) or field_ref
    return find_field_value(data, leaf)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part for part in re.split(r"[\s,]+", text) if part]


def _as_number(value: Any) -> float | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _threshold(pack: dict[str, Any], name: str, default: float | int | None = None) -> float | int | None:
    thresholds = pack.get("thresholds") or {}
    if name in thresholds:
        return thresholds[name]
    return default


def _parse_dt(value: Any) -> datetime | None:
    text = _as_str(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return _as_str(value) == ""


def _any_section_filled(data: dict[str, Any], prefix: str) -> bool:
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if prefix and not (key.startswith(prefix) or f"/{prefix}" in key or key.startswith(prefix.rstrip("/"))):
            # Also match keys containing the prefix segment
            if prefix.rstrip("/") not in key:
                continue
        if not _is_blank(value):
            return True
    return False


_REF_KEYS = (
    "field",
    "parent_field",
    "trigger_field",
    "text_field",
    "start_field",
    "end_field",
    "child_field",
)
_REF_LIST_KEYS = ("fields", "child_fields")


def collect_field_refs(node: Any, out: list[str] | None = None) -> list[str]:
    """Walk a check/details tree and collect logical field references."""
    if out is None:
        out = []
    if not isinstance(node, dict):
        return out
    for key in _REF_KEYS:
        value = node.get(key)
        if value:
            text = str(value).strip()
            if text and text not in out:
                out.append(text)
    for key in _REF_LIST_KEYS:
        for item in node.get(key) or []:
            text = str(item).strip()
            if text and text not in out:
                out.append(text)
    for nested_key in ("check", "if", "then", "failed", "inner"):
        if nested_key in node:
            collect_field_refs(node[nested_key], out)
    for child in node.get("checks") or []:
        collect_field_refs(child, out)
    return out


def find_data_key(data: dict[str, Any], field_name: str | None) -> str | None:
    if not field_name:
        return None
    if field_name in data:
        return field_name
    suffix = f"/{field_name}"
    for key in data:
        if key.endswith(suffix):
            return key
    return None


def _iso_naive(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _related_submission_ref(row: Submission) -> dict[str, Any]:
    return {
        "submissionId": row.id,
        "koboId": row.kobo_id,
        "enumerator": row.enumerator,
        "submittedAt": _iso_naive(row.submitted_at),
        "projectName": row.project.name if row.project is not None else row.form_name,
    }


def find_related_submissions(
    *,
    pack: dict[str, Any],
    field_ref: str | None,
    value: str,
    project_rows: list[Submission],
) -> list[dict[str, Any]]:
    if not field_ref or not value:
        return []
    related: list[dict[str, Any]] = []
    for row in project_rows:
        row_data = row.data if isinstance(row.data, dict) else {}
        other = _as_str(get_value(row_data, pack, field_ref))
        if other == value:
            related.append(_related_submission_ref(row))
    return related


def enrich_flag_related_submissions(
    *,
    pack: dict[str, Any] | None,
    rule: dict[str, Any] | None,
    details: dict[str, Any] | None,
    project_rows: list[Submission],
) -> list[dict[str, Any]]:
    """Resolve sibling submissions for uniqueness / sample-cap flags."""
    if not isinstance(details, dict):
        return []
    existing = details.get("relatedSubmissions")
    if isinstance(existing, list) and existing:
        return [item for item in existing if isinstance(item, dict)]
    if not pack:
        return []
    op = str(details.get("op") or "")
    value = _as_str(details.get("value"))
    if not value or op not in {"unique_in_project", "group_count_lte"}:
        # Also recover op/field from the rule check when older flags lack them.
        check = (rule or {}).get("check") if rule else None
        if isinstance(check, dict) and check.get("op") in {"unique_in_project", "group_count_lte"}:
            op = str(check.get("op"))
            field_ref = check.get("field")
            if not value:
                return []
            return find_related_submissions(
                pack=pack, field_ref=field_ref, value=value, project_rows=project_rows
            )
        return []
    field_ref = None
    if rule:
        check = rule.get("check")
        if isinstance(check, dict):
            field_ref = check.get("field")
    if not field_ref:
        return []
    return find_related_submissions(
        pack=pack, field_ref=field_ref, value=value, project_rows=project_rows
    )


def resolve_highlight_fields(
    *,
    pack: dict[str, Any],
    check: dict[str, Any] | None,
    details: dict[str, Any] | None,
    data: dict[str, Any],
) -> list[str]:
    """Return submission data keys (and special markers) to highlight for a flag."""
    refs = collect_field_refs(check)
    collect_field_refs(details, refs)
    keys: list[str] = []

    op = str((details or {}).get("op") or (check or {}).get("op") or "")
    if op == "gps_present":
        for marker in ("_geolocation", "__location__"):
            if marker not in keys:
                keys.append(marker)
    if op == "attachment_count_gte":
        if "_attachments" not in keys:
            keys.append("_attachments")
    if op == "duration_minutes_gte":
        for meta in ("start", "end"):
            found = find_data_key(data, meta)
            if found and found not in keys:
                keys.append(found)
            elif meta not in keys:
                keys.append(meta)

    for ref in refs:
        leaf = resolve_alias(pack, ref) or ref
        found = find_data_key(data, leaf)
        candidate = found or leaf
        if candidate not in keys:
            keys.append(candidate)
    return keys


def highlight_fields_for_flag(
    *,
    pack: dict[str, Any] | None,
    rule: dict[str, Any] | None,
    details: dict[str, Any] | None,
    data: dict[str, Any],
) -> list[str]:
    if isinstance(details, dict) and details.get("highlightFields"):
        existing = details.get("highlightFields")
        if isinstance(existing, list) and existing:
            return [str(x) for x in existing]
    if not pack:
        return []
    check = None
    if rule:
        check = rule.get("check")
        if check is None and rule.get("checks"):
            check = {"op": "all", "checks": rule["checks"]}
    return resolve_highlight_fields(pack=pack, check=check, details=details, data=data)


def eval_check(
    check: dict[str, Any] | None,
    *,
    data: dict[str, Any],
    pack: dict[str, Any],
    project_rows: list[Submission] | None = None,
    current: Submission | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (passes, details). Flag when passes is False."""
    if not check or not isinstance(check, dict):
        return True, {}
    op = str(check.get("op") or "").strip()
    details: dict[str, Any] = {"op": op}

    if op == "all":
        for child in check.get("checks") or []:
            ok, child_details = eval_check(
                child, data=data, pack=pack, project_rows=project_rows, current=current
            )
            if not ok:
                return False, {"op": op, "failed": child_details}
        return True, details

    if op == "any":
        for child in check.get("checks") or []:
            ok, child_details = eval_check(
                child, data=data, pack=pack, project_rows=project_rows, current=current
            )
            if ok:
                return True, details
        return False, details

    if op == "not":
        ok, child_details = eval_check(
            check.get("check"), data=data, pack=pack, project_rows=project_rows, current=current
        )
        return (not ok), {"op": op, "inner": child_details}

    if op == "if_then":
        if_ok, if_details = eval_check(
            check.get("if"), data=data, pack=pack, project_rows=project_rows, current=current
        )
        # if condition is the "trigger" in natural language; when trigger holds, then must hold.
        # Convention: `if` check PASSES when the antecedent is true.
        if not if_ok:
            return True, details  # antecedent false → rule N/A
        then_ok, then_details = eval_check(
            check.get("then"), data=data, pack=pack, project_rows=project_rows, current=current
        )
        return then_ok, {"op": op, "if": if_details, "then": then_details}

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
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        expected = _as_str(check.get("value")).lower()
        details.update({"value": value, "expected": expected})
        return value == expected, details

    if op == "equals_any":
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        values = {_as_str(v).lower() for v in (check.get("values") or [])}
        details.update({"value": value, "expected": list(values)})
        return value in values, details

    if op == "not_equals":
        value = _as_str(get_value(data, pack, check.get("field"))).lower()
        expected = _as_str(check.get("value")).lower()
        return value != expected, {"value": value, "expected": expected}

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
        num = _as_number(get_value(data, pack, check.get("field")))
        bound = check.get("value")
        if bound is None and check.get("threshold"):
            bound = _threshold(pack, str(check["threshold"]))
        details.update({"value": num, "bound": bound})
        if num is None or bound is None:
            return False, details
        bound_f = float(bound)
        if op == "gt":
            return num > bound_f, details
        if op == "lt":
            return num < bound_f, details
        if op == "gte":
            return num >= bound_f, details
        return num <= bound_f, details

    if op == "integer":
        text = _as_str(get_value(data, pack, check.get("field")))
        ok = bool(re.fullmatch(r"-?\d+", text))
        return ok, {"value": text}

    if op == "duration_minutes_gte":
        start = _parse_dt(get_value(data, pack, check.get("start_field") or "start"))
        end = _parse_dt(get_value(data, pack, check.get("end_field") or "end"))
        # Kobo also stores start/end as top-level meta sometimes
        if start is None:
            start = _parse_dt(data.get("start"))
        if end is None:
            end = _parse_dt(data.get("end"))
        minimum = check.get("min")
        if minimum is None:
            minimum = _threshold(pack, str(check.get("threshold") or "min_duration_minutes"), 15)
        details.update({"start": start.isoformat() if start else None, "end": end.isoformat() if end else None, "min": minimum})
        if start is None or end is None or minimum is None:
            return True, details  # cannot evaluate → do not flag
        minutes = (end - start).total_seconds() / 60.0
        details["minutes"] = minutes
        return minutes >= float(minimum), details

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
    return True, details


def evaluate_rule(
    rule: dict[str, Any],
    *,
    data: dict[str, Any],
    pack: dict[str, Any],
    project_rows: list[Submission] | None,
    current: Submission,
) -> DqaFlag | None:
    check = rule.get("check")
    if check is None and rule.get("checks"):
        check = {"op": "all", "checks": rule["checks"]}
    # Rules describe FLAG conditions. Pack authors can set flag_when: "fail" (default)
    # meaning we flag when the check does NOT pass. Or flag_when: "pass" for rare cases.
    ok, details = eval_check(
        check, data=data, pack=pack, project_rows=project_rows, current=current
    )
    flag_when = str(rule.get("flag_when") or "fail").lower()
    should_flag = (not ok) if flag_when == "fail" else ok
    if not should_flag:
        return None
    submission_data = data if isinstance(data, dict) else {}
    highlight = resolve_highlight_fields(
        pack=pack, check=check, details=details, data=submission_data
    )
    enriched = dict(details or {})
    if highlight:
        enriched["highlightFields"] = highlight
    return DqaFlag(
        id=str(uuid.uuid4()),
        submission_id=current.id,
        project_id=current.project_id,
        rule_id=str(rule.get("id") or "unknown"),
        severity=str(rule.get("severity") or "amber").lower(),
        title=str(rule.get("title") or rule.get("id") or "Flag"),
        message=str(rule.get("message") or rule.get("title") or "Rule failed"),
        details=enriched,
        evaluated_at=_now(),
    )


def load_seed_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    if not SEED_DIR.exists():
        return packs
    for path in sorted(SEED_DIR.glob("*.yml")) + sorted(SEED_DIR.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed reading seed pack %s", path)
            continue
        if isinstance(payload, dict):
            packs.append(payload)
    return packs


def get_pack_for_project(db: Session, project_id: str) -> dict[str, Any] | None:
    row = db.get(RulePack, project_id)
    if row and isinstance(row.pack, dict) and row.pack:
        return row.pack
    project = db.get(Project, project_id)
    uid = project.uid if project else project_id
    for seed in load_seed_packs():
        uids = seed.get("project_uids") or []
        if project_id in uids or uid in uids or seed.get("id") == project_id:
            return seed
    return None


def seed_rule_packs(db: Session, *, overwrite: bool = False) -> int:
    """Import YAML seeds into rule_packs for matching projects. Returns count written."""
    projects = {p.id: p for p in db.scalars(select(Project)).all()}
    by_uid = {p.uid: p for p in projects.values()}
    written = 0
    for seed in load_seed_packs():
        targets: list[Project] = []
        for uid in seed.get("project_uids") or []:
            if uid in projects:
                targets.append(projects[uid])
            elif uid in by_uid:
                targets.append(by_uid[uid])
        for project in targets:
            existing = db.get(RulePack, project.id)
            if existing and not overwrite:
                continue
            if existing:
                existing.pack = seed
                existing.updated_at = _now()
            else:
                db.add(RulePack(project_id=project.id, pack=seed, updated_at=_now()))
            written += 1
    if written:
        db.commit()
    return written


def save_pack(db: Session, project_id: str, pack: dict[str, Any]) -> dict[str, Any]:
    row = db.get(RulePack, project_id)
    if row:
        row.pack = pack
        row.updated_at = _now()
    else:
        row = RulePack(project_id=project_id, pack=pack, updated_at=_now())
        db.add(row)
    db.commit()
    db.refresh(row)
    return row.pack


def evaluate_submission(
    db: Session,
    submission: Submission,
    *,
    pack: dict[str, Any] | None = None,
    project_rows: list[Submission] | None = None,
    commit: bool = True,
) -> list[DqaFlag]:
    pack = pack or get_pack_for_project(db, submission.project_id)
    db.execute(delete(DqaFlag).where(DqaFlag.submission_id == submission.id))
    if not pack:
        if commit:
            db.commit()
        return []

    data = submission.data if isinstance(submission.data, dict) else {}
    flags: list[DqaFlag] = []
    for rule in pack.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        flag = evaluate_rule(
            rule,
            data=data,
            pack=pack,
            project_rows=project_rows,
            current=submission,
        )
        if flag:
            flags.append(flag)
            db.add(flag)

    has_red = any(f.severity == "red" for f in flags)
    if has_red:
        submission.status = "flagged"
    elif submission.status == "flagged":
        submission.status = "validated"

    if commit:
        db.commit()
    return flags


def evaluate_project(db: Session, project_id: str) -> dict[str, int]:
    pack = get_pack_for_project(db, project_id)
    rows = list(
        db.scalars(
            select(Submission).where(Submission.project_id == project_id)
        ).all()
    )
    flagged_submissions = 0
    total_flags = 0
    for submission in rows:
        flags = evaluate_submission(
            db,
            submission,
            pack=pack,
            project_rows=rows,
            commit=False,
        )
        total_flags += len(flags)
        if flags:
            flagged_submissions += 1
    db.commit()
    return {
        "submissions": len(rows),
        "flagged_submissions": flagged_submissions,
        "flags": total_flags,
    }


def prefer_label_text(label: Any) -> str:
    """Pick a readable label from Kobo bilingual arrays (prefer English when last)."""
    if label is None:
        return ""
    if isinstance(label, list):
        parts = [str(x).strip() for x in label if str(x).strip()]
        if not parts:
            return ""
        # Kobo bilingual labels are usually [Hindi, English]
        return parts[-1] if len(parts) > 1 else parts[0]
    if isinstance(label, dict):
        for key in ("en", "English", "english"):
            if label.get(key):
                return str(label[key]).strip()
        parts = [str(v).strip() for v in label.values() if str(v).strip()]
        return parts[-1] if parts else ""
    return str(label).strip()


def list_form_fields(form_definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(form_definition, dict):
        return []
    survey = form_definition.get("survey") or []
    choices = form_definition.get("choices") or []
    by_list: dict[str, list[dict[str, Any]]] = {}
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        list_name = str(choice.get("list_name") or "")
        by_list.setdefault(list_name, []).append(
            {
                "name": str(choice.get("name") or ""),
                "label": prefer_label_text(choice.get("label")),
            }
        )

    skip = {
        "start",
        "end",
        "begin_group",
        "end_group",
        "begin_repeat",
        "end_repeat",
        "note",
        "calculate",
        "acknowledge",
    }
    fields: list[dict[str, Any]] = []
    for item in survey:
        if not isinstance(item, dict):
            continue
        qtype = str(item.get("type") or "")
        name = str(item.get("name") or "")
        if not name or qtype in skip or qtype.startswith("begin_") or qtype.startswith("end_"):
            continue
        list_name = item.get("select_from_list_name")
        fields.append(
            {
                "name": name,
                "type": qtype,
                "label": prefer_label_text(item.get("label")) or name,
                "list_name": list_name,
                "choices": by_list.get(str(list_name), []) if list_name else [],
            }
        )
    # Always expose Kobo meta start/end if present in submissions convention
    fields.extend(
        [
            {
                "name": "start",
                "type": "datetime",
                "label": "Start time",
                "list_name": None,
                "choices": [],
            },
            {
                "name": "end",
                "type": "datetime",
                "label": "End time",
                "list_name": None,
                "choices": [],
            },
        ]
    )
    return fields
