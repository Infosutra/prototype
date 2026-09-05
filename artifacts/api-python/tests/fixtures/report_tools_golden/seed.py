"""Golden-report fixture: representative study rows for report-tool lock-in.

Study window
------------
- study id: study-golden
- start: 2026-03-01
- report / execution date: 2026-03-15 (Asia/Kolkata)
- org: Infosutra Golden Org

Edge-case matrix (must appear in tool goldens)
----------------------------------------------
- Red enumerator (prior-day RED only — keeps today free of RED so
  red_priority_items hits the today-empty → cumulative fallback).
  Covered on enumerator_performance_study as RedOnly / PriorRedBucket*.
  Intentionally absent from enumerator_performance_today.
- Amber-only enumerator today
- Clean enumerator today
- Rules today vs cumulative-only (top_failing_rules scopes diverge)
- RED with no submissions today → red_priority fallback (~daily_stats 193)
- Median duration below 0.85× group median → "(below)" label
- flag_pct >= 12 with zero red → "Verify flagged records"
- Tool T3 with zero flags → "No material DQA flags…"
- Tool T2 with amber + red in top rules → combined narrative
- Volume for top-12 / top-15 / top-5 / top-25 cuts and ruleId tie-breaks

Timezone note: "today" for 2026-03-15 in Asia/Kolkata is
[2026-03-14 18:30:00, 2026-03-15 18:29:59.999999] UTC-naive.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models import AppSettings, DqaFlag, Project, Study, StudyTool, Submission

STUDY_ID = "study-golden"
REPORT_DATE = "2026-03-15"
STUDY_START = "2026-03-01"
TIMEZONE = "Asia/Kolkata"
ORG_NAME = "Infosutra Golden Org"
LAST_SYNC = datetime(2026, 3, 15, 3, 0, 0)  # fixed → lastKoboPullDisplay

# Local-day anchors (UTC-naive, matching day_bounds for Asia/Kolkata).
TODAY = datetime(2026, 3, 15, 6, 0, 0)  # firmly inside today
PRIOR = datetime(2026, 3, 10, 8, 0, 0)  # firmly before today


def _sub(
    *,
    sid: str,
    project_id: str,
    enumerator: str,
    submitted_at: datetime,
    minutes: float | None = 40.0,
    udise: str | None = None,
    form_name: str = "Form",
) -> Submission:
    data: dict = {}
    if minutes is not None:
        start = submitted_at
        end = submitted_at + timedelta(minutes=minutes)
        data["start"] = start.isoformat()
        data["end"] = end.isoformat()
    if udise is not None:
        data["udise"] = udise
    return Submission(
        id=sid,
        project_id=project_id,
        kobo_id=sid,
        form_id=f"form-{project_id}",
        form_name=form_name,
        enumerator=enumerator,
        submitted_at=submitted_at,
        status="complete",
        data=data,
        created_at=submitted_at,
    )


def _flag(
    *,
    fid: str,
    submission_id: str,
    project_id: str,
    rule_id: str,
    severity: str,
    title: str,
    evaluated_at: datetime,
    message: str = "",
) -> DqaFlag:
    return DqaFlag(
        id=fid,
        submission_id=submission_id,
        project_id=project_id,
        rule_id=rule_id,
        severity=severity,
        title=title,
        message=message or f"{rule_id} failed",
        evaluated_at=evaluated_at,
    )


def seed_golden_study(db: Session) -> Study:
    """Insert the golden study graph. Caller owns commit lifecycle after return."""
    if db.get(AppSettings, "settings") is None:
        db.add(
            AppSettings(
                id="settings",
                organization_name=ORG_NAME,
                ai_enabled=False,
            )
        )

    study = Study(
        id=STUDY_ID,
        name="Golden Fixture Study",
        start_date=STUDY_START,
        timezone=TIMEZONE,
        created_at=datetime(2026, 3, 1),
        updated_at=datetime(2026, 3, 1),
    )
    db.add(study)

    tools = [
        StudyTool(id="tool-t1", study_id=STUDY_ID, code="T1", label="Facility", target_count=100, sort_order=0),
        StudyTool(id="tool-t2", study_id=STUDY_ID, code="T2", label="Teachers", target_count=50, sort_order=1),
        StudyTool(id="tool-t3", study_id=STUDY_ID, code="T3", label="Clean Form", target_count=20, sort_order=2),
    ]
    projects = [
        Project(
            id="proj-t1",
            uid="uid-t1",
            name="Facility Survey",
            study_id=STUDY_ID,
            study_tool_id="tool-t1",
            last_sync_at=LAST_SYNC,
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        ),
        Project(
            id="proj-t2",
            uid="uid-t2",
            name="Teachers Survey",
            study_id=STUDY_ID,
            study_tool_id="tool-t2",
            last_sync_at=LAST_SYNC,
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        ),
        Project(
            id="proj-t3",
            uid="uid-t3",
            name="Clean Survey",
            study_id=STUDY_ID,
            study_tool_id="tool-t3",
            last_sync_at=LAST_SYNC,
            created_at=datetime(2026, 3, 1),
            updated_at=datetime(2026, 3, 1),
        ),
    ]
    db.add_all(tools)
    db.add_all(projects)
    db.flush()

    subs: list[Submission] = []
    flags: list[DqaFlag] = []

    # --- Named enumerators (domain-rule edge cases) -------------------------
    # RedOnly: prior-day RED only (enables red_priority today→cumulative fallback).
    subs.append(
        _sub(
            sid="sub-redonly-1",
            project_id="proj-t1",
            enumerator="RedOnly",
            submitted_at=PRIOR,
            minutes=45.0,
            udise="11111111",
            form_name="Facility Survey",
        )
    )
    flags.append(
        _flag(
            fid="flag-redonly-1",
            submission_id="sub-redonly-1",
            project_id="proj-t1",
            rule_id="PRIOR_RED_A",
            severity="red",
            title="Prior GPS missing",
            evaluated_at=PRIOR,
        )
    )

    # AmberOnly: today, amber flags only (no red).
    for i in range(3):
        sid = f"sub-amberonly-{i}"
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator="AmberOnly",
                submitted_at=TODAY + timedelta(minutes=i),
                minutes=42.0,
                form_name="Facility Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-amberonly-{i}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id=f"TODAY_AMBER_{i:02d}",
                severity="amber",
                title=f"Today amber {i:02d}",
                evaluated_at=TODAY + timedelta(minutes=i),
            )
        )

    # CleanToday: today, no flags.
    subs.append(
        _sub(
            sid="sub-clean-1",
            project_id="proj-t3",
            enumerator="CleanToday",
            submitted_at=TODAY + timedelta(minutes=30),
            minutes=40.0,
            form_name="Clean Survey",
        )
    )

    # FastBelow: short interview; peers below push group median up → "(below)".
    # Uses study-window (prior) rows so enumerator_performance_study sees them.
    subs.append(
        _sub(
            sid="sub-fast-1",
            project_id="proj-t1",
            enumerator="FastBelow",
            submitted_at=PRIOR + timedelta(hours=1),
            minutes=10.0,  # well under 0.85 × ~40
            form_name="Facility Survey",
        )
    )
    # Amber-only flags so flag_pct can be high without red → Verify branch.
    # 1 flagged of 1 submission on FastBelow alone isn't enough once we add
    # more rows; give FastBelow 8 prior clean + 2 amber = 20% flagged, 0 red.
    for i in range(8):
        subs.append(
            _sub(
                sid=f"sub-fast-clean-{i}",
                project_id="proj-t1",
                enumerator="FastBelow",
                submitted_at=PRIOR + timedelta(hours=2, minutes=i),
                minutes=10.0,
                form_name="Facility Survey",
            )
        )
    for i in range(2):
        sid = f"sub-fast-amber-{i}"
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator="FastBelow",
                submitted_at=PRIOR + timedelta(hours=3, minutes=i),
                minutes=10.0,
                form_name="Facility Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-fast-amber-{i}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id=f"FAST_AMBER_{i}",
                severity="amber",
                title=f"Fast amber {i}",
                evaluated_at=PRIOR + timedelta(hours=3, minutes=i),
            )
        )
    # FastBelow: 11 subs, 2 flagged amber → flag_pct ≈ 18.2%, red=0, short median.

    # VerifyOnly: longer median (~40) so not "(below)"; high amber flag rate, 0 red.
    for i in range(10):
        sid = f"sub-verify-{i}"
        flagged = i < 2  # 2/10 = 20%
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator="VerifyOnly",
                submitted_at=PRIOR + timedelta(days=1, minutes=i),
                minutes=40.0,
                form_name="Facility Survey",
            )
        )
        if flagged:
            flags.append(
                _flag(
                    fid=f"flag-verify-{i}",
                    submission_id=sid,
                    project_id="proj-t1",
                    rule_id=f"VERIFY_AMBER_{i}",
                    severity="amber",
                    title=f"Verify amber {i}",
                    evaluated_at=PRIOR + timedelta(days=1, minutes=i),
                )
            )

    # --- Today amber rules for top_failing_rules today (≥13 rules, ties) ----
    # Counts: R00..R04 count=3, R05..R09 count=2, R10..R14 count=1
    # All on AmberOnly so we do not create many 100%-flagged pad enumerators
    # that crowd FastBelow/VerifyOnly out of the study top-25.
    today_rule_counts = (
        [(f"TODAY_R{i:02d}", 3) for i in range(5)]
        + [(f"TODAY_R{i:02d}", 2) for i in range(5, 10)]
        + [(f"TODAY_R{i:02d}", 1) for i in range(10, 15)]
    )
    today_slot = 0
    for rule_id, count in today_rule_counts:
        for j in range(count):
            sid = f"sub-today-rule-{today_slot:03d}"
            today_slot += 1
            submitted = TODAY + timedelta(minutes=40 + today_slot)
            subs.append(
                _sub(
                    sid=sid,
                    project_id="proj-t1",
                    enumerator="AmberOnly",
                    submitted_at=submitted,
                    minutes=40.0,
                    form_name="Facility Survey",
                )
            )
            flags.append(
                _flag(
                    fid=f"flag-today-rule-{today_slot:03d}",
                    submission_id=sid,
                    project_id="proj-t1",
                    rule_id=rule_id,
                    severity="amber",
                    title=f"Today rule {rule_id}",
                    evaluated_at=submitted,
                )
            )

    # Cumulative-only rules (never on today) so scopes diverge — one enumerator.
    for i in range(8):
        sid = f"sub-cumul-only-{i}"
        rule_id = f"CUMUL_ONLY_{i:02d}"
        submitted = PRIOR + timedelta(days=2, minutes=i)
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator="CumulFarm",
                submitted_at=submitted,
                minutes=40.0,
                form_name="Facility Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-cumul-only-{i}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id=rule_id,
                severity="amber",
                title=f"Cumulative only {i:02d}",
                evaluated_at=submitted,
            )
        )

    # --- Prior-day RED groups for red_priority top-15 + fallback -------------
    # 16 distinct tool+rule RED groups on T1 (no today reds).
    # Keep enumerator cardinality low so FastBelow / VerifyOnly survive the
    # enumerator_performance_study top-25 cut (sorted by redFlags first).
    for i in range(16):
        sid = f"sub-prior-red-{i:02d}"
        rule_id = f"PRIOR_RED_{i:02d}"
        submitted = PRIOR + timedelta(days=3, minutes=i)
        enum = f"PriorRedBucket{i % 3}"
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator=enum,
                submitted_at=submitted,
                minutes=40.0,
                udise=f"200000{i:02d}",
                form_name="Facility Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-prior-red-{i:02d}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id=rule_id,
                severity="red",
                title=f"Prior red {i:02d}",
                evaluated_at=submitted,
            )
        )
    # Extra rows on PRIOR_RED_00..03 so those groups have count=2 (ordering).
    for i in range(4):
        sid = f"sub-prior-red-extra-{i}"
        rule_id = f"PRIOR_RED_{i:02d}"
        submitted = PRIOR + timedelta(days=3, hours=1, minutes=i)
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t1",
                enumerator=f"PriorRedBucket{i % 3}",
                submitted_at=submitted,
                minutes=40.0,
                udise=f"210000{i:02d}",
                form_name="Facility Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-prior-red-extra-{i}",
                submission_id=sid,
                project_id="proj-t1",
                rule_id=rule_id,
                severity="red",
                title=f"Prior red {i:02d}",
                evaluated_at=submitted,
            )
        )

    # --- T2: amber + red rules for findings_by_tool combined narrative ------
    for i in range(4):
        sid = f"sub-t2-amber-{i}"
        submitted = PRIOR + timedelta(days=4, minutes=i)
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t2",
                enumerator="T2AmberLead",
                submitted_at=submitted,
                minutes=40.0,
                form_name="Teachers Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-t2-amber-{i}",
                submission_id=sid,
                project_id="proj-t2",
                rule_id="T2_AMBER_LEAD",
                severity="amber",
                title="T2 leading amber",
                evaluated_at=submitted,
            )
        )
    for i in range(2):
        sid = f"sub-t2-red-{i}"
        submitted = PRIOR + timedelta(days=4, hours=1, minutes=i)
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t2",
                enumerator="T2RedCluster",
                submitted_at=submitted,
                minutes=40.0,
                udise=f"300000{i:02d}",
                form_name="Teachers Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-t2-red-{i}",
                submission_id=sid,
                project_id="proj-t2",
                rule_id="T2_RED_CLUSTER",
                severity="red",
                title="T2 red cluster",
                evaluated_at=submitted,
            )
        )
    # Extra distinct T2 rules so top-5 cut is meaningful (≥6 rules).
    for i in range(5):
        sid = f"sub-t2-extra-{i}"
        submitted = PRIOR + timedelta(days=4, hours=2, minutes=i)
        rule_id = f"T2_EXTRA_{i:02d}"
        subs.append(
            _sub(
                sid=sid,
                project_id="proj-t2",
                enumerator="T2ExtraFarm",
                submitted_at=submitted,
                minutes=40.0,
                form_name="Teachers Survey",
            )
        )
        flags.append(
            _flag(
                fid=f"flag-t2-extra-{i}",
                submission_id=sid,
                project_id="proj-t2",
                rule_id=rule_id,
                severity="amber",
                title=f"T2 extra {i:02d}",
                evaluated_at=submitted,
            )
        )

    # --- T3: zero-flag tool (plus CleanToday already added) -----------------
    # Stay on PRIOR calendar day (do not use +days that land in report-date IST).
    for i in range(5):
        subs.append(
            _sub(
                sid=f"sub-t3-clean-{i}",
                project_id="proj-t3",
                enumerator=f"T3Clean{i}",
                submitted_at=PRIOR + timedelta(hours=5, minutes=i),
                minutes=40.0,
                form_name="Clean Survey",
            )
        )

    # --- Pad enumerators to force top-25 cut on enumerator_performance_study
    # Clean pads (flagRate 0) sort after FastBelow/VerifyOnly.
    existing_enums = {
        "RedOnly",
        "AmberOnly",
        "CleanToday",
        "FastBelow",
        "VerifyOnly",
        "CumulFarm",
        "PriorRedBucket0",
        "PriorRedBucket1",
        "PriorRedBucket2",
        "T2AmberLead",
        "T2RedCluster",
        "T2ExtraFarm",
        *[f"T3Clean{i}" for i in range(5)],
    }
    pad_idx = 0
    while len(existing_enums) < 28:
        name = f"EnumPad{pad_idx:02d}"
        if name in existing_enums:
            pad_idx += 1
            continue
        existing_enums.add(name)
        subs.append(
            _sub(
                sid=f"sub-enum-pad-{pad_idx:02d}",
                project_id="proj-t1",
                enumerator=name,
                submitted_at=PRIOR + timedelta(hours=6, minutes=pad_idx),
                minutes=40.0,
                form_name="Facility Survey",
            )
        )
        pad_idx += 1

    # Peer medians at 40 min so FastBelow (10) is clearly below 0.85× group median.
    # (Most pads already use 40.)

    db.add_all(subs)
    db.add_all(flags)
    db.commit()
    db.refresh(study)
    return study
