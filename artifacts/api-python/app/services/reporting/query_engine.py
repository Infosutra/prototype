"""SQL query compiler for ReportSpec Query IR.

Primary window filter: ``calendar_day`` inclusive between
``ResolvedTimeWindow.from_date`` and ``to_date`` (study-local days). This keeps
``groupBy: day`` consistent with the window. ``utc_start`` / exclusive ``utc_end``
are available on the window for callers that prefer ``submitted_at`` bounds.

Always scopes via denormalized ``study_id``. Column identifiers come only from
catalog allowlist maps — never interpolated from raw LLM strings.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, case, func, select
from sqlalchemy.orm import Session

from app.domain.reporting.catalog import (
    FLAG_ROW_COLUMNS,
    FieldRef,
    JoinNeed,
    Project,
    StudyTool,
    DqaFlag,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
    resolve_field,
    validate_identifier,
)
from app.domain.reporting.query import Filter, Measure, Query
from app.domain.time_window import ResolvedTimeWindow
from app.services.reporting.config import ReportingConfig, get_reporting_config

class QueryError(Exception):
    """Invalid Query IR or compilation failure."""


def run(
    db: Session,
    query: Query,
    *,
    study_id: str,
    window: ResolvedTimeWindow,
    config: ReportingConfig | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    cfg = config or get_reporting_config()
    entity = query.entity
    if entity not in {"submission", "flag", "answer"}:
        raise QueryError(f"Unknown entity '{entity}'")

    group_by = list(query.group_by or [])
    if len(group_by) > cfg.query_group_by_max:
        raise QueryError(
            f"groupBy has {len(group_by)} fields; max is {cfg.query_group_by_max}"
        )

    for name in group_by:
        try:
            validate_identifier(name)
            ref = resolve_field(entity, name)
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        if ref.kind != "dimension":
            raise QueryError(f"Cannot groupBy fact '{name}'")

    measures = list(query.measures) if query.measures is not None else None
    if measures is not None and len(measures) == 0:
        raise QueryError("measures must be non-empty when provided")

    if entity == "answer" and measures is not None:
        _require_field_key_eq(query.filters)

    limit = query.limit if query.limit is not None else cfg.query_limit_default
    if limit < 1:
        raise QueryError("limit must be >= 1")
    limit = min(limit, cfg.query_limit_max)

    try:
        stmt, col_keys = _compile(
            query,
            entity=entity,
            study_id=study_id,
            window=window,
            group_by=group_by,
            measures=measures,
            limit=limit,
        )
    except ValueError as exc:
        raise QueryError(str(exc)) from exc

    rows = db.execute(stmt).mappings().all()
    result_rows = [_row_to_dict(row, col_keys) for row in rows]

    if measures is not None and not group_by:
        if not result_rows:
            return {m.id: 0 if m.fn.startswith("count") else None for m in measures}
        return result_rows[0]
    return result_rows


def _require_field_key_eq(filters: list[Filter]) -> None:
    for f in filters:
        if f.field == "fieldKey" and f.op == "eq" and f.value is not None:
            return
    raise QueryError("answer aggregates require a fieldKey eq filter")


def _row_to_dict(row: Any, keys: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in keys:
        val = row[key]
        if hasattr(val, "isoformat") and not isinstance(val, str):
            # date / datetime → ISO string for JSON-friendly output
            try:
                out[key] = val.isoformat()
            except Exception:
                out[key] = val
        else:
            out[key] = val
    return out


def _compile(
    query: Query,
    *,
    entity: str,
    study_id: str,
    window: ResolvedTimeWindow,
    group_by: list[str],
    measures: list[Measure] | None,
    limit: int,
) -> tuple[Select[Any], list[str]]:
    needs: set[JoinNeed] = set()
    field_refs: dict[str, FieldRef] = {}

    def use_field(name: str) -> FieldRef:
        try:
            validate_identifier(name)
            ref = resolve_field(entity, name)
        except ValueError as exc:
            raise QueryError(str(exc)) from exc
        field_refs[name] = ref
        needs.update(ref.joins)
        return ref

    for name in group_by:
        use_field(name)

    if measures is not None:
        for m in measures:
            try:
                validate_identifier(m.id)
            except ValueError as exc:
                raise QueryError(str(exc)) from exc
            if m.field:
                use_field(m.field)
    else:
        # Row list defaults
        if entity == "flag":
            for name in FLAG_ROW_COLUMNS:
                use_field(name)
        elif entity == "submission":
            for name in ("enumerator", "projectId", "day"):
                use_field(name)
        else:
            for name in ("fieldKey", "enumerator", "day"):
                use_field(name)

    for f in query.filters:
        use_field(f.field)

    if query.sort is not None:
        use_field(query.sort.field)

    # Base FROM + study + calendar_day window
    if entity == "submission":
        stmt = select().select_from(Submission)
        study_col = Submission.study_id
        day_col = Submission.calendar_day
    elif entity == "flag":
        stmt = select().select_from(DqaFlag)
        study_col = DqaFlag.study_id
        # day comes via submission join; ensure submission for window
        needs.add("submission")
        day_col = Submission.calendar_day
    else:
        stmt = select().select_from(SubmissionAnswer)
        study_col = SubmissionAnswer.study_id
        needs.add("submission")
        day_col = Submission.calendar_day

    stmt = _apply_joins(stmt, entity=entity, needs=needs)

    clauses = [
        study_col == study_id,
        day_col >= window.from_date,
        day_col <= window.to_date,
    ]
    for f in query.filters:
        clauses.append(_filter_clause(use_field(f.field), f))

    stmt = stmt.where(and_(*clauses))

    select_cols: list[Any] = []
    col_keys: list[str] = []

    if measures is None:
        for name in field_refs:
            # Stable order: flag row cols first if applicable
            pass
        ordered = (
            list(FLAG_ROW_COLUMNS)
            if entity == "flag"
            else list(field_refs.keys())
        )
        # Ensure all used dimension fields appear
        for name in ordered:
            if name not in field_refs:
                continue
            select_cols.append(field_refs[name].column.label(name))
            col_keys.append(name)
        for name, ref in field_refs.items():
            if name not in col_keys:
                select_cols.append(ref.column.label(name))
                col_keys.append(name)
        stmt = stmt.with_only_columns(*select_cols)
    else:
        for name in group_by:
            select_cols.append(field_refs[name].column.label(name))
            col_keys.append(name)
        for m in measures:
            select_cols.append(_measure_expr(m, field_refs).label(m.id))
            col_keys.append(m.id)
        stmt = stmt.with_only_columns(*select_cols)
        if group_by:
            stmt = stmt.group_by(*[field_refs[n].column for n in group_by])

    if query.sort is not None:
        sort_ref = field_refs[query.sort.field]
        order = sort_ref.column.asc() if query.sort.dir == "asc" else sort_ref.column.desc()
        stmt = stmt.order_by(order)
    elif group_by:
        stmt = stmt.order_by(*[field_refs[n].column.asc() for n in group_by])

    stmt = stmt.limit(limit)
    return stmt, col_keys


def _apply_joins(stmt: Select[Any], *, entity: str, needs: set[JoinNeed]) -> Select[Any]:
    """Attach needed joins. project is via submission or flag.project_id."""
    joined_submission = False
    joined_project = False

    if entity == "flag" and "submission" in needs:
        stmt = stmt.join(Submission, Submission.id == DqaFlag.submission_id)
        joined_submission = True

    if entity == "answer" and "submission" in needs:
        stmt = stmt.join(Submission, Submission.id == SubmissionAnswer.submission_id)
        joined_submission = True

    if entity == "submission" and "quality" in needs:
        stmt = stmt.outerjoin(
            SubmissionQuality, SubmissionQuality.submission_id == Submission.id
        )

    if "project" in needs or "study_tool" in needs:
        if entity == "submission":
            stmt = stmt.outerjoin(Project, Project.id == Submission.project_id)
            joined_project = True
        elif entity == "flag":
            if not joined_submission and "submission" in needs:
                stmt = stmt.join(Submission, Submission.id == DqaFlag.submission_id)
                joined_submission = True
            stmt = stmt.outerjoin(Project, Project.id == DqaFlag.project_id)
            joined_project = True
        elif entity == "answer":
            if not joined_submission:
                stmt = stmt.join(
                    Submission, Submission.id == SubmissionAnswer.submission_id
                )
                joined_submission = True
            stmt = stmt.outerjoin(Project, Project.id == Submission.project_id)
            joined_project = True

    if "study_tool" in needs:
        if not joined_project:
            if entity == "submission":
                stmt = stmt.outerjoin(Project, Project.id == Submission.project_id)
            elif entity == "flag":
                stmt = stmt.outerjoin(Project, Project.id == DqaFlag.project_id)
            else:
                stmt = stmt.outerjoin(Project, Project.id == Submission.project_id)
        stmt = stmt.outerjoin(StudyTool, StudyTool.id == Project.study_tool_id)

    return stmt


def _filter_clause(ref: FieldRef, f: Filter) -> Any:
    col = ref.column
    op = f.op
    if op == "eq":
        return col == f.value
    if op == "neq":
        return col != f.value
    if op == "in":
        return col.in_(list(f.value))
    if op == "isTrue":
        return col.is_(True)
    if op == "isFalse":
        return col.is_(False)
    if op == "gt":
        return col > f.value
    if op == "gte":
        return col >= f.value
    if op == "lt":
        return col < f.value
    if op == "lte":
        return col <= f.value
    raise QueryError(f"Unknown filter op '{op}'")


def _measure_expr(m: Measure, field_refs: dict[str, FieldRef]) -> Any:
    fn = m.fn
    if fn == "count":
        # Count rows of the primary entity
        return func.count()
    if m.field is None:
        raise QueryError(f"Measure '{m.id}' requires field")
    ref = field_refs[m.field]
    col = ref.column
    if fn == "countDistinct":
        return func.count(func.distinct(col))
    if fn == "countWhere":
        return func.sum(case((col == m.eq, 1), else_=0))
    if fn == "sum":
        return func.sum(col)
    if fn == "avg":
        return func.avg(col)
    if fn == "min":
        return func.min(col)
    if fn == "max":
        return func.max(col)
    raise QueryError(f"Unknown measure fn '{fn}'")
