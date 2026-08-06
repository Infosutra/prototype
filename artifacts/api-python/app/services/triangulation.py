"""UDISE-joined triangulation views (TR-1, TR-3, TR-5). Local DB only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, Submission
from app.schemas.dqa import (
    TriangulationLink,
    TriangulationPracticeStat,
    TriangulationRow,
    TriangulationViewOut,
)
from app.services.dqa_engine import find_field_value, get_pack_for_project, get_value
from app.services.studies import SIGHTSAVERS_2030_FORMS, SIGHTSAVERS_2030_ID

# Fallback UIDs only when no study tool_code mapping is available.
_SEED_UID = {entry["toolCode"]: entry["projectUid"] for entry in SIGHTSAVERS_2030_FORMS}

# TR-1: self-report D4 codes ↔ classroom observation items.
# Observed = CO value in {"1","2"} (clearly / partially observed).
TR1_PRACTICES: list[dict[str, Any]] = [
    {
        "id": "front_seating",
        "label": "Appropriate / front seating",
        "claim_codes": {"e"},
        "observe_field": "CO1",
    },
    {
        "id": "differentiated",
        "label": "Differentiated tasks / materials",
        "claim_codes": {"a"},
        "observe_field": "CO2",
    },
    {
        "id": "multi_sensory_visual",
        "label": "Visual supports / multi-sensory",
        "claim_codes": {"b", "c"},
        "observe_field": "CO3",
    },
    {
        "id": "peer_group",
        "label": "Peer support / inclusive group work",
        "claim_codes": {"d", "f"},
        "observe_field": "CO4",
    },
    {
        "id": "adapted_materials",
        "label": "Adapted materials / assistive use",
        "claim_codes": {"h"},
        "observe_field": "CO8",
    },
]

SUPPORTED_VIEWS = {
    "TR-1": "Teacher practice: claimed vs observed",
    "TR-3": "Governance activity: school vs parents",
    "TR-5": "CWD identification consistency",
}


def _iso(value) -> str | None:
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
        project_name=sub.project_name,
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


def _observed(value: Any) -> bool:
    return str(value or "").strip() in {"1", "2"}


def _project(db: Session, tool: str, *, study_id: str | None = None) -> Project | None:
    """Resolve a study form by tool code (T1/T2/T3). Prefer active study membership."""
    code = tool.strip().upper()
    sid = study_id or SIGHTSAVERS_2030_ID

    if sid:
        row = db.scalars(
            select(Project).where(Project.study_id == sid, Project.tool_code == code)
        ).first()
        if row:
            return row

    # Any form with this tool code
    row = db.scalars(select(Project).where(Project.tool_code == code)).first()
    if row:
        return row

    # Seed UID fallback (legacy Sightsavers demo)
    uid = _SEED_UID.get(code)
    if not uid:
        return None
    return db.get(Project, uid) or db.scalars(select(Project).where(Project.uid == uid)).first()


def list_triangulation_views() -> list[dict[str, str]]:
    return [{"id": k, "title": v} for k, v in SUPPORTED_VIEWS.items()]


def build_view(
    db: Session, view_id: str, *, study_id: str | None = None
) -> TriangulationViewOut:
    key = view_id.strip().upper().replace("_", "-")
    aliases = {
        "TR-1": "TR-1",
        "CLAIMED-VS-OBSERVED": "TR-1",
        "TR-3": "TR-3",
        "GOVERNANCE": "TR-3",
        "TR-5": "TR-5",
        "CWD-IDENTIFICATION": "TR-5",
    }
    resolved = aliases.get(key) or aliases.get(view_id.strip().lower())
    if not resolved:
        raise KeyError(view_id)
    if resolved == "TR-1":
        return _build_tr1(db, study_id=study_id)
    if resolved == "TR-3":
        return _build_tr3(db, study_id=study_id)
    return _build_tr5(db, study_id=study_id)


def _build_tr5(db: Session, *, study_id: str | None = None) -> TriangulationViewOut:
    facility = _project(db, "T1", study_id=study_id)
    teachers = _project(db, "T2", study_id=study_id)
    parents = _project(db, "T3", study_id=study_id)
    facility_pack = get_pack_for_project(db, facility.id) if facility else None
    teacher_pack = get_pack_for_project(db, teachers.id) if teachers else None
    parent_pack = get_pack_for_project(db, parents.id) if parents else None

    facility_by_udise: dict[str, tuple[Submission, str]] = {}
    if facility and facility_pack:
        for row in db.scalars(select(Submission).where(Submission.project_id == facility.id)):
            data = row.data if isinstance(row.data, dict) else {}
            udise = str(get_value(data, facility_pack, "udise") or "").strip()
            if not udise:
                continue
            name = str(get_value(data, facility_pack, "institution_name") or row.project_name)
            existing = facility_by_udise.get(udise)
            if existing is None or _is_newer(row, existing[0]):
                facility_by_udise[udise] = (row, name)

    teacher_has: dict[str, bool] = {}
    teacher_link: dict[str, Submission] = {}
    if teachers and teacher_pack:
        for row in db.scalars(select(Submission).where(Submission.project_id == teachers.id)):
            data = row.data if isinstance(row.data, dict) else {}
            udise = str(get_value(data, teacher_pack, "udise") or "").strip()
            if not udise:
                continue
            has = _yes(get_value(data, teacher_pack, "has_cwd"))
            teacher_has[udise] = teacher_has.get(udise, False) or has
            current = teacher_link.get(udise)
            if current is None:
                teacher_link[udise] = row
            else:
                current_has = _yes(
                    get_value(
                        current.data if isinstance(current.data, dict) else {},
                        teacher_pack,
                        "has_cwd",
                    )
                )
                if (not has) and current_has:
                    teacher_link[udise] = row
                elif has == current_has and _is_newer(row, current):
                    teacher_link[udise] = row

    parent_has: dict[str, bool] = {}
    parent_link: dict[str, Submission] = {}
    if parents and parent_pack:
        for row in db.scalars(select(Submission).where(Submission.project_id == parents.id)):
            data = row.data if isinstance(row.data, dict) else {}
            udise = str(get_value(data, parent_pack, "udise") or "").strip()
            if not udise:
                continue
            has = _yes(find_field_value(data, "P5"))
            parent_has[udise] = parent_has.get(udise, False) or has
            current = parent_link.get(udise)
            if current is None:
                parent_link[udise] = row
            else:
                current_has = _yes(
                    find_field_value(
                        current.data if isinstance(current.data, dict) else {},
                        "P5",
                    )
                )
                if has and not current_has:
                    parent_link[udise] = row
                elif has == current_has and _is_newer(row, current):
                    parent_link[udise] = row

    all_udise = sorted(set(facility_by_udise) | set(teacher_has) | set(parent_has))
    rows: list[TriangulationRow] = []
    mismatch = 0
    for udise in all_udise:
        fac = facility_by_udise.get(udise)
        t_has = teacher_has.get(udise)
        p_has = parent_has.get(udise)
        is_mismatch = bool(p_has) and t_has is False
        if is_mismatch:
            mismatch += 1
        rows.append(
            TriangulationRow(
                udise=udise,
                school_name=(fac[1] if fac else None),
                facility=_link(fac[0] if fac else None),
                teacher=_link(teacher_link.get(udise)),
                parent=_link(parent_link.get(udise)),
                teacher_has_cwd=t_has,
                parent_reports_disability=p_has,
                mismatch=is_mismatch,
            )
        )
    return TriangulationViewOut(
        id="TR-5",
        title=SUPPORTED_VIEWS["TR-5"],
        description=(
            "Where parents report a child with disability at an institution, "
            "teachers there should report having CWD in class."
        ),
        rows=rows,
        mismatch_count=mismatch,
        practices=[],
    )


def _build_tr1(db: Session, *, study_id: str | None = None) -> TriangulationViewOut:
    teachers = _project(db, "T2", study_id=study_id)
    if not teachers:
        return TriangulationViewOut(
            id="TR-1",
            title=SUPPORTED_VIEWS["TR-1"],
            description="No Teachers form synced.",
            rows=[],
            mismatch_count=0,
            practices=[],
        )
    pack = get_pack_for_project(db, teachers.id) or {"fields": {}}
    rows_data = list(db.scalars(select(Submission).where(Submission.project_id == teachers.id)))

    practice_claimed = {p["id"]: 0 for p in TR1_PRACTICES}
    practice_observed = {p["id"]: 0 for p in TR1_PRACTICES}
    practice_n = {p["id"]: 0 for p in TR1_PRACTICES}

    rows: list[TriangulationRow] = []
    mismatch = 0
    for row in rows_data:
        data = row.data if isinstance(row.data, dict) else {}
        udise = str(get_value(data, pack, "udise") or "").strip() or "—"
        school = str(get_value(data, pack, "institution_name") or "") or None
        claimed_codes = set(_as_list(get_value(data, pack, "practice_d4") or find_field_value(data, "D4")))
        claimed_labels: list[str] = []
        observed_labels: list[str] = []
        gap = 0
        for practice in TR1_PRACTICES:
            pid = practice["id"]
            claimed = bool(claimed_codes & practice["claim_codes"])
            obs_val = find_field_value(data, practice["observe_field"])
            observed = _observed(obs_val)
            # Only count denominators when observation had an opportunity (not "4")
            if str(obs_val or "").strip() != "4":
                practice_n[pid] += 1
                if claimed:
                    practice_claimed[pid] += 1
                if observed:
                    practice_observed[pid] += 1
            if claimed:
                claimed_labels.append(practice["label"])
            if observed:
                observed_labels.append(practice["label"])
            if claimed and not observed and str(obs_val or "").strip() in {"3", "2", "1"}:
                # claimed but not clearly/partially? if 3 = not observed → gap
                if not observed:
                    gap += 1
        is_mismatch = gap > 0
        if is_mismatch:
            mismatch += 1
        rows.append(
            TriangulationRow(
                udise=udise,
                school_name=school,
                teacher=_link(row),
                claimed_practices=claimed_labels,
                observed_practices=observed_labels,
                practice_gap=gap,
                mismatch=is_mismatch,
            )
        )

    practices: list[TriangulationPracticeStat] = []
    for practice in TR1_PRACTICES:
        pid = practice["id"]
        n = practice_n[pid] or 1
        claimed_pct = round(100.0 * practice_claimed[pid] / n, 1)
        observed_pct = round(100.0 * practice_observed[pid] / n, 1)
        # Concordance among teachers who claimed: share also observed
        denom = practice_claimed[pid] or 1
        # Approximate concordance as min(observed,claimed)/max(claimed,1) style agreement on rates
        concordance = round(100.0 - abs(claimed_pct - observed_pct), 1)
        practices.append(
            TriangulationPracticeStat(
                id=pid,
                label=practice["label"],
                claimed_count=practice_claimed[pid],
                observed_count=practice_observed[pid],
                n=practice_n[pid],
                claimed_pct=claimed_pct,
                observed_pct=observed_pct,
                concordance_pct=max(0.0, concordance),
                gap_pct=round(max(0.0, claimed_pct - observed_pct), 1),
            )
        )

    return TriangulationViewOut(
        id="TR-1",
        title=SUPPORTED_VIEWS["TR-1"],
        description=(
            "Compare teacher self-reported inclusive practices (D4) with classroom "
            "observation (CO1–CO8). Expect observed ≤ claimed; large gaps flag over-reporting."
        ),
        rows=rows,
        mismatch_count=mismatch,
        practices=practices,
    )


def _build_tr3(db: Session, *, study_id: str | None = None) -> TriangulationViewOut:
    facility = _project(db, "T1", study_id=study_id)
    parents = _project(db, "T3", study_id=study_id)
    facility_pack = get_pack_for_project(db, facility.id) if facility else None
    parent_pack = get_pack_for_project(db, parents.id) if parents else None

    school: dict[str, dict[str, Any]] = {}
    if facility and facility_pack:
        for row in db.scalars(select(Submission).where(Submission.project_id == facility.id)):
            data = row.data if isinstance(row.data, dict) else {}
            udise = str(get_value(data, facility_pack, "udise") or "").strip()
            if not udise:
                continue
            meetings_raw = get_value(data, facility_pack, "meetings_held")
            try:
                meetings = int(float(str(meetings_raw).strip())) if meetings_raw not in (None, "") else 0
            except ValueError:
                meetings = 0
            cwd = _yes(get_value(data, facility_pack, "cwd_discussed"))
            name = str(get_value(data, facility_pack, "institution_name") or "") or None
            existing = school.get(udise)
            if existing is None or _is_newer(row, existing["sub"]):
                school[udise] = {
                    "sub": row,
                    "name": name,
                    "meetings": meetings,
                    "cwd": cwd,
                    "active": meetings > 0 and cwd,
                }

    parent_agg: dict[str, dict[str, Any]] = {}
    if parents and parent_pack:
        for row in db.scalars(select(Submission).where(Submission.project_id == parents.id)):
            data = row.data if isinstance(row.data, dict) else {}
            udise = str(get_value(data, parent_pack, "udise") or "").strip()
            if not udise:
                continue
            attended = _yes(get_value(data, parent_pack, "attended_pta"))
            issues = _yes(get_value(data, parent_pack, "pta_issues"))
            bucket = parent_agg.setdefault(
                udise,
                {"attended": False, "issues": False, "sub": None},
            )
            bucket["attended"] = bucket["attended"] or attended
            bucket["issues"] = bucket["issues"] or issues
            if bucket["sub"] is None or _is_newer(row, bucket["sub"]):
                bucket["sub"] = row

    all_udise = sorted(set(school) | set(parent_agg))
    rows: list[TriangulationRow] = []
    mismatch = 0
    for udise in all_udise:
        sch = school.get(udise)
        par = parent_agg.get(udise)
        school_active = bool(sch and sch["active"])
        parent_attended = bool(par and par["attended"])
        parent_issues = bool(par and par["issues"])
        # Paper governance: school claims active inclusive PTA but parents don't confirm
        is_mismatch = school_active and not (parent_attended and parent_issues)
        if is_mismatch:
            mismatch += 1
        rows.append(
            TriangulationRow(
                udise=udise,
                school_name=(sch["name"] if sch else None),
                facility=_link(sch["sub"] if sch else None),
                parent=_link(par["sub"] if par else None),
                school_meetings=(sch["meetings"] if sch else None),
                school_cwd_discussed=(sch["cwd"] if sch else None),
                school_governance_active=school_active if sch else None,
                parent_attended_pta=parent_attended if par else None,
                parent_cwd_issues=parent_issues if par else None,
                mismatch=is_mismatch,
            )
        )

    return TriangulationViewOut(
        id="TR-3",
        title=SUPPORTED_VIEWS["TR-3"],
        description=(
            "Schools reporting PTA/SMC meetings with CWD discussion should have "
            "parents who report attending and discussing CWD issues."
        ),
        rows=rows,
        mismatch_count=mismatch,
        practices=[],
    )
