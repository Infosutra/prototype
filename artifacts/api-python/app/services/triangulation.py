"""Study-defined triangulation evaluators (cross_form_join, claim_vs_observation)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, StudyTool, Submission, TriangulationView
from app.schemas.dqa import (
    TriangulationCell,
    TriangulationColumn,
    TriangulationLink,
    TriangulationPracticeStat,
    TriangulationRow,
    TriangulationViewOut,
)
from app.services.dqa_engine import get_pack_for_project, get_value


class TriangulationError(ValueError):
    """Raised for missing study / unknown view (mapped to 4xx by the router)."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _link(sub: Submission | None) -> TriangulationLink | None:
    if not sub:
        return None
    return TriangulationLink(
        submission_id=sub.id,
        kobo_id=sub.kobo_id,
        enumerator=sub.enumerator,
        submitted_at=_iso(sub.submitted_at),
        project_name=sub.project.name if sub.project is not None else sub.form_name,
    )


def _is_newer(candidate: Submission, current: Submission | None) -> bool:
    if current is None:
        return True
    if candidate.submitted_at is None:
        return False
    return current.submitted_at is None or candidate.submitted_at > current.submitted_at


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [p for p in text.replace(",", " ").split() if p]


def _yes(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "yes", "y", "true"}


def _require_study_id(study_id: str | None) -> str:
    sid = (study_id or "").strip()
    if not sid:
        raise TriangulationError("studyId is required", status_code=400)
    return sid


def _project_for_tool(db: Session, study_id: str, tool: str) -> Project | None:
    code = tool.strip().upper()
    return db.scalars(
        select(Project)
        .join(StudyTool, Project.study_tool_id == StudyTool.id)
        .where(Project.study_id == study_id, StudyTool.code == code)
    ).first()


def _columns_from_def(definition: dict[str, Any]) -> list[TriangulationColumn]:
    cols: list[TriangulationColumn] = []
    for col in definition.get("columns") or []:
        if not isinstance(col, dict):
            continue
        key = str(col.get("key") or "").strip()
        if not key:
            continue
        as_kind = str(col.get("as") or col.get("kind") or "text").strip()
        kind = {"yes_no": "bool", "bool": "bool", "number": "number", "list": "list"}.get(
            as_kind, "text"
        )
        cols.append(
            TriangulationColumn(
                key=key,
                label=str(col.get("label") or key),
                kind=kind,
            )
        )
    return cols


def _cell(key: str, label: str, value: Any, kind: str) -> TriangulationCell:
    return TriangulationCell(key=key, label=label, value=value, kind=kind)


def _cast_value(raw: Any, as_kind: str) -> Any:
    kind = (as_kind or "text").strip()
    if kind == "bool" or kind == "yes_no":
        return _yes(raw)
    if kind == "bool_any":
        return _yes(raw)
    if kind == "int_or_zero":
        try:
            return int(float(str(raw).strip())) if raw not in (None, "") else 0
        except ValueError:
            return 0
    if kind == "text":
        text = str(raw or "").strip()
        return text or None
    return raw


def _resolve_path(ctx: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    cur: Any = ctx
    for part in parts:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _eval_pred(pred: Any, ctx: dict[str, Any]) -> bool:
    if not isinstance(pred, dict):
        return bool(pred)
    if "all" in pred:
        items = pred["all"] or []
        return all(_eval_pred(p, ctx) for p in items)
    if "not" in pred:
        return not _eval_pred(pred["not"], ctx)
    if "is_true" in pred:
        return bool(_resolve_path(ctx, str(pred["is_true"])))
    if "is_false" in pred:
        return _resolve_path(ctx, str(pred["is_false"])) is False
    if "gt" in pred:
        pair = pred["gt"]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return False
        left = _resolve_path(ctx, str(pair[0])) if isinstance(pair[0], str) else pair[0]
        right = pair[1]
        try:
            return float(left) > float(right)
        except (TypeError, ValueError):
            return False
    return False


def _pick_submission(
    rows: list[Submission],
    pack: dict[str, Any],
    pick: dict[str, Any] | None,
) -> Submission | None:
    if not rows:
        return None
    pool = list(rows)
    prefer = (pick or {}).get("prefer")
    if isinstance(prefer, dict) and prefer.get("alias") is not None:
        alias = str(prefer["alias"])
        want = prefer.get("value")
        matching: list[Submission] = []
        for row in pool:
            data = row.data if isinstance(row.data, dict) else {}
            raw = get_value(data, pack, alias)
            if isinstance(want, bool):
                if _yes(raw) == want:
                    matching.append(row)
            else:
                if str(raw or "").strip() == str(want).strip():
                    matching.append(row)
        if matching:
            pool = matching
    # then: latest
    best: Submission | None = None
    for row in pool:
        if _is_newer(row, best):
            best = row
    return best


def _group_by_join(
    db: Session, project: Project, pack: dict[str, Any]
) -> dict[str, list[Submission]]:
    join_alias = str(pack.get("join_key") or "udise")
    groups: dict[str, list[Submission]] = {}
    for row in db.scalars(select(Submission).where(Submission.project_id == project.id)):
        data = row.data if isinstance(row.data, dict) else {}
        key = str(get_value(data, pack, join_alias) or "").strip()
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    return groups


def _build_cross_form_join(
    db: Session,
    study_id: str,
    view: TriangulationView,
) -> TriangulationViewOut:
    definition = view.definition if isinstance(view.definition, dict) else {}
    participants = definition.get("participants") or []
    # role -> join_key -> {fields..., "_sub": Submission|None, "_present": bool}
    per_role: dict[str, dict[str, dict[str, Any]]] = {}

    for part in participants:
        if not isinstance(part, dict):
            continue
        role = str(part.get("role") or "").strip()
        tool = str(part.get("tool") or "").strip()
        if not role or not tool:
            continue
        project = _project_for_tool(db, study_id, tool)
        pack = get_pack_for_project(db, project.id) if project else None
        buckets: dict[str, dict[str, Any]] = {}
        if project and pack:
            groups = _group_by_join(db, project, pack)
            for join_key, rows in groups.items():
                picked = _pick_submission(rows, pack, part.get("pick") if isinstance(part.get("pick"), dict) else None)
                fields: dict[str, Any] = {"_sub": picked, "_present": True}
                derive = part.get("derive") or {}
                if isinstance(derive, dict) and picked is not None:
                    data = picked.data if isinstance(picked.data, dict) else {}
                    for fname, spec in derive.items():
                        if not isinstance(spec, dict):
                            continue
                        alias = str(spec.get("alias") or "")
                        as_kind = str(spec.get("as") or "text")
                        raw = get_value(data, pack, alias)
                        if as_kind == "text" and not raw:
                            if alias == "institution_name":
                                raw = (
                                    picked.project.name
                                    if picked.project is not None
                                    else picked.form_name
                                )
                        fields[fname] = _cast_value(raw, as_kind)
                reduce = part.get("reduce") or {}
                if isinstance(reduce, dict):
                    for fname, spec in reduce.items():
                        if not isinstance(spec, dict):
                            continue
                        alias = str(spec.get("alias") or "")
                        as_kind = str(spec.get("as") or "text")
                        values = [
                            get_value(
                                r.data if isinstance(r.data, dict) else {},
                                pack,
                                alias,
                            )
                            for r in rows
                        ]
                        if as_kind == "bool_any":
                            fields[fname] = any(_yes(v) for v in values)
                        else:
                            fields[fname] = _cast_value(
                                values[-1] if values else None, as_kind
                            )
                buckets[join_key] = fields
        per_role[role] = buckets
    all_keys: set[str] = set()
    for buckets in per_role.values():
        all_keys |= set(buckets.keys())

    computed_specs = definition.get("computed") or {}
    mismatch_spec = definition.get("mismatch")
    columns = _columns_from_def(definition)
    rows_out: list[TriangulationRow] = []
    mismatch_count = 0

    for join_key in sorted(all_keys):
        ctx: dict[str, Any] = {"join_key": join_key}
        links: dict[str, TriangulationLink | None] = {}
        for role, buckets in per_role.items():
            bucket = buckets.get(join_key)
            if bucket is None:
                ctx[role] = {}
                links[role] = None
                continue
            role_ctx = {k: v for k, v in bucket.items() if not k.startswith("_")}
            ctx[role] = role_ctx
            links[role] = _link(bucket.get("_sub"))

        if isinstance(computed_specs, dict):
            for path, pred in computed_specs.items():
                parts = str(path).split(".", 1)
                if len(parts) != 2:
                    continue
                role, fname = parts
                role_ctx = ctx.setdefault(role, {})
                if isinstance(role_ctx, dict):
                    role_ctx[fname] = _eval_pred(pred, ctx)

        is_mismatch = bool(_eval_pred(mismatch_spec, ctx)) if mismatch_spec else False
        if is_mismatch:
            mismatch_count += 1

        cells: list[TriangulationCell] = []
        for col in columns:
            if col.key == "join_key":
                val: Any = join_key
            else:
                val = _resolve_path(ctx, col.key)
            cells.append(_cell(col.key, col.label, val, col.kind))

        rows_out.append(
            TriangulationRow(
                key=join_key,
                cells=cells,
                links=links,
                mismatch=is_mismatch,
            )
        )

    return TriangulationViewOut(
        id=view.code,
        title=view.title or definition.get("title") or view.code,
        description=view.description or definition.get("description"),
        columns=columns,
        rows=rows_out,
        mismatch_count=mismatch_count,
        practices=[],
    )


def _build_claim_vs_observation(
    db: Session,
    study_id: str,
    view: TriangulationView,
) -> TriangulationViewOut:
    definition = view.definition if isinstance(view.definition, dict) else {}
    tool = str(definition.get("tool") or "").strip()
    claim_alias = str(definition.get("claim_alias") or "").strip()
    obs_cfg = definition.get("observation") or {}
    observed_values = {str(v) for v in (obs_cfg.get("observed_values") or ["1", "2"])}
    no_opportunity = str(obs_cfg.get("no_opportunity_value") or "4")
    gap_value = str(obs_cfg.get("gap_value") or "3")
    items = definition.get("items") or []

    columns = _columns_from_def(definition)
    if not columns:
        columns = [
            TriangulationColumn(key="join_key", label="UDISE", kind="text"),
            TriangulationColumn(key="school_name", label="School", kind="text"),
            TriangulationColumn(key="claimed_practices", label="Claimed", kind="list"),
            TriangulationColumn(key="observed_practices", label="Observed", kind="list"),
            TriangulationColumn(key="practice_gap", label="Gap", kind="number"),
        ]

    project = _project_for_tool(db, study_id, tool) if tool else None
    if not project:
        return TriangulationViewOut(
            id=view.code,
            title=view.title,
            description=view.description or f"No form synced for tool {tool}.",
            columns=columns,
            rows=[],
            mismatch_count=0,
            practices=[],
        )

    pack = get_pack_for_project(db, project.id) or {"fields": {}, "join_key": "udise"}
    join_alias = str(pack.get("join_key") or "udise")
    rows_data = list(db.scalars(select(Submission).where(Submission.project_id == project.id)))

    practice_claimed = {str(p["id"]): 0 for p in items if isinstance(p, dict) and p.get("id")}
    practice_observed = {pid: 0 for pid in practice_claimed}
    practice_n = {pid: 0 for pid in practice_claimed}

    rows_out: list[TriangulationRow] = []
    mismatch_count = 0

    for row in rows_data:
        data = row.data if isinstance(row.data, dict) else {}
        join_key = str(get_value(data, pack, join_alias) or "").strip() or "—"
        school = str(get_value(data, pack, "institution_name") or "") or None
        claimed_codes = set(_as_list(get_value(data, pack, claim_alias)))
        claimed_labels: list[str] = []
        observed_labels: list[str] = []
        gap = 0

        for practice in items:
            if not isinstance(practice, dict):
                continue
            pid = str(practice.get("id") or "")
            if not pid:
                continue
            claim_codes = {str(c).strip() for c in (practice.get("claim_codes") or [])}
            claimed = bool(claimed_codes & claim_codes)
            obs_alias = str(practice.get("observe_alias") or "")
            obs_val = get_value(data, pack, obs_alias) if obs_alias else None
            obs_str = str(obs_val or "").strip()
            observed = obs_str in observed_values

            # Denominator: count only when observation had an opportunity
            if obs_str != no_opportunity:
                practice_n[pid] = practice_n.get(pid, 0) + 1
                if claimed:
                    practice_claimed[pid] = practice_claimed.get(pid, 0) + 1
                if observed:
                    practice_observed[pid] = practice_observed.get(pid, 0) + 1
            if claimed:
                claimed_labels.append(str(practice.get("label") or pid))
            if observed:
                observed_labels.append(str(practice.get("label") or pid))
            # Gap: claimed AND observation value is exactly gap_value ("3")
            if claimed and obs_str == gap_value:
                gap += 1

        is_mismatch = gap > 0
        if is_mismatch:
            mismatch_count += 1

        values = {
            "join_key": join_key,
            "school_name": school,
            "claimed_practices": claimed_labels,
            "observed_practices": observed_labels,
            "practice_gap": gap,
        }
        cells = [
            _cell(col.key, col.label, values.get(col.key), col.kind)
            for col in columns
        ]
        rows_out.append(
            TriangulationRow(
                key=join_key,
                cells=cells,
                links={"teacher": _link(row)},
                mismatch=is_mismatch,
            )
        )

    practices: list[TriangulationPracticeStat] = []
    for practice in items:
        if not isinstance(practice, dict):
            continue
        pid = str(practice.get("id") or "")
        if not pid:
            continue
        n = practice_n.get(pid, 0) or 1
        claimed_pct = round(100.0 * practice_claimed.get(pid, 0) / n, 1)
        observed_pct = round(100.0 * practice_observed.get(pid, 0) / n, 1)
        concordance = round(100.0 - abs(claimed_pct - observed_pct), 1)
        practices.append(
            TriangulationPracticeStat(
                id=pid,
                label=str(practice.get("label") or pid),
                claimed_count=practice_claimed.get(pid, 0),
                observed_count=practice_observed.get(pid, 0),
                n=practice_n.get(pid, 0),
                claimed_pct=claimed_pct,
                observed_pct=observed_pct,
                concordance_pct=max(0.0, concordance),
                gap_pct=round(max(0.0, claimed_pct - observed_pct), 1),
            )
        )

    return TriangulationViewOut(
        id=view.code,
        title=view.title or definition.get("title") or view.code,
        description=view.description or definition.get("description"),
        columns=columns,
        rows=rows_out,
        mismatch_count=mismatch_count,
        practices=practices,
    )


def list_views(db: Session, study_id: str | None) -> list[dict[str, str]]:
    sid = _require_study_id(study_id)
    rows = db.scalars(
        select(TriangulationView)
        .where(TriangulationView.study_id == sid)
        .order_by(TriangulationView.code)
    ).all()
    return [{"id": r.code, "title": r.title or r.code} for r in rows]


def get_view_row(db: Session, study_id: str, code: str) -> TriangulationView | None:
    return db.scalars(
        select(TriangulationView).where(
            TriangulationView.study_id == study_id,
            TriangulationView.code == code,
        )
    ).first()


def build_view(
    db: Session, view_id: str, *, study_id: str | None = None
) -> TriangulationViewOut:
    sid = _require_study_id(study_id)
    code = view_id.strip()
    # Accept TR_1 style
    normalized = code.upper().replace("_", "-")
    view = get_view_row(db, sid, code) or get_view_row(db, sid, normalized)
    if view is None:
        # try case-insensitive
        for row in db.scalars(
            select(TriangulationView).where(TriangulationView.study_id == sid)
        ).all():
            if row.code.upper().replace("_", "-") == normalized:
                view = row
                break
    if view is None:
        raise TriangulationError(f"Unknown triangulation view: {view_id}", status_code=404)

    definition = view.definition if isinstance(view.definition, dict) else {}
    kind = str(definition.get("kind") or "").strip()
    if kind == "cross_form_join":
        return _build_cross_form_join(db, sid, view)
    if kind == "claim_vs_observation":
        return _build_claim_vs_observation(db, sid, view)
    raise TriangulationError(
        f"Unsupported triangulation kind: {kind or '(missing)'}",
        status_code=400,
    )


def list_definition_rows(db: Session, study_id: str) -> list[TriangulationView]:
    return list(
        db.scalars(
            select(TriangulationView)
            .where(TriangulationView.study_id == study_id)
            .order_by(TriangulationView.code)
        ).all()
    )


def upsert_view(
    db: Session,
    study_id: str,
    *,
    code: str,
    title: str,
    description: str | None,
    definition: dict[str, Any],
    view_id: str | None = None,
) -> TriangulationView:
    import uuid

    code_clean = code.strip()
    existing = get_view_row(db, study_id, code_clean)
    if existing is None and view_id:
        existing = db.get(TriangulationView, view_id)
        if existing and existing.study_id != study_id:
            existing = None
    if existing is None:
        existing = TriangulationView(
            id=view_id or f"tview-{uuid.uuid4().hex[:12]}",
            study_id=study_id,
            code=code_clean,
        )
        db.add(existing)
    existing.code = code_clean
    existing.title = title.strip() or code_clean
    existing.description = description
    existing.definition = definition
    # Keep kind/code/title in definition in sync when present
    if isinstance(existing.definition, dict):
        existing.definition = {
            **existing.definition,
            "code": code_clean,
            "title": existing.title,
        }
        if description is not None:
            existing.definition["description"] = description
    db.commit()
    db.refresh(existing)
    return existing


def delete_view(db: Session, view: TriangulationView) -> None:
    db.delete(view)
    db.commit()


def seed_triangulation_views(db: Session, study_id: str) -> int:
    """Upsert seed triangulation definitions for a study (no overwrite of custom edits if codes exist — update definition from seed when empty)."""
    from app.seeds import load_triangulation_seed_definitions
    import uuid

    seeded = 0
    for definition in load_triangulation_seed_definitions():
        code = str(definition.get("code") or "").strip()
        if not code:
            continue
        existing = get_view_row(db, study_id, code)
        title = str(definition.get("title") or code)
        description = definition.get("description")
        if isinstance(description, str):
            description = description.strip() or None
        if existing is None:
            db.add(
                TriangulationView(
                    id=f"tview-{uuid.uuid4().hex[:12]}",
                    study_id=study_id,
                    code=code,
                    title=title,
                    description=description,
                    definition=definition,
                )
            )
            seeded += 1
        else:
            # Keep seed defs fresh for the default study on startup
            existing.title = title
            existing.description = description
            existing.definition = definition
            seeded += 1
    if seeded:
        db.commit()
    return seeded
