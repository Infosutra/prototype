"""Shared Phase 2/3 golden reporting DB fixture (Meena/Ravi/Arun 25/20/5)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from app.db.models import (
    DqaFlag,
    Project,
    Study,
    StudyTool,
    Submission,
    SubmissionAnswer,
    SubmissionQuality,
)

STUDY_ID = "study-golden"
OTHER_STUDY = "study-other"
EXECUTION_DATE = "2026-09-12"
TZ = "Asia/Kolkata"
DAY = date(2026, 9, 12)
OLDER_DAY = date(2026, 9, 8)


def seed_golden_reporting(db: Session) -> None:
    """Seed the golden study used by query-engine and execute tests.

    Meena 8 clean; Ravi 12 (2 amber); Arun 5 (3 red) on 2026-09-12 Asia/Kolkata
    → total 25, clean 20, flagged 5.
    """
    study = Study(
        id=STUDY_ID,
        name="Golden",
        start_date="2026-08-01",
        timezone=TZ,
    )
    other = Study(id=OTHER_STUDY, name="Other", timezone=TZ)
    db.add_all([study, other])
    db.flush()

    tool = StudyTool(
        id="tool-t1",
        study_id=STUDY_ID,
        code="T1",
        label="Household",
        target_count=100,
        sort_order=0,
    )
    db.add(tool)
    db.flush()

    project = Project(
        id="proj-golden",
        uid="proj-golden",
        name="Form A",
        study_id=STUDY_ID,
        study_tool_id=tool.id,
        form_definition={"survey": [], "choices": []},
    )
    other_project = Project(
        id="proj-other",
        uid="proj-other",
        name="Other form",
        study_id=OTHER_STUDY,
        form_definition={"survey": [], "choices": []},
    )
    orphan_project = Project(
        id="proj-orphan",
        uid="proj-orphan",
        name="Orphan",
        study_id=None,
        form_definition={"survey": [], "choices": []},
    )
    db.add_all([project, other_project, orphan_project])
    db.flush()

    def add_sub(
        *,
        kobo_id: str,
        enumerator: str,
        calendar_day: date,
        is_clean: bool,
        max_severity: str | None = None,
        flag_count: int = 0,
        red_count: int = 0,
        amber_count: int = 0,
        study_id: str | None = STUDY_ID,
        project_id: str = "proj-golden",
        duration: float = 30.0,
    ) -> Submission:
        hour = 10 + (int(kobo_id) % 8)
        submitted = datetime(
            calendar_day.year, calendar_day.month, calendar_day.day, hour, 0, 0
        )
        sub = Submission(
            id=f"{project_id}:{kobo_id}",
            kobo_id=kobo_id,
            project_id=project_id,
            study_id=study_id,
            form_id=project_id,
            form_name="Form",
            enumerator=enumerator,
            submitted_at=submitted,
            data={"_id": int(kobo_id), "note": "archive only"},
            duration_minutes=duration,
            calendar_day=calendar_day,
            status="pending",
        )
        db.add(sub)
        db.flush()
        if study_id is not None:
            db.add(
                SubmissionQuality(
                    submission_id=sub.id,
                    study_id=study_id,
                    project_id=project_id,
                    is_clean=is_clean,
                    max_severity=max_severity,
                    flag_count=flag_count,
                    red_count=red_count,
                    amber_count=amber_count,
                )
            )
        return sub

    for i in range(8):
        add_sub(kobo_id=str(100 + i), enumerator="Meena", calendar_day=DAY, is_clean=True)

    ravi_flagged: list[Submission] = []
    for i in range(12):
        flagged = i < 2
        sub = add_sub(
            kobo_id=str(200 + i),
            enumerator="Ravi",
            calendar_day=DAY,
            is_clean=not flagged,
            max_severity="amber" if flagged else None,
            flag_count=1 if flagged else 0,
            amber_count=1 if flagged else 0,
        )
        if flagged:
            ravi_flagged.append(sub)

    arun_flagged: list[Submission] = []
    for i in range(5):
        flagged = i < 3
        sub = add_sub(
            kobo_id=str(300 + i),
            enumerator="Arun",
            calendar_day=DAY,
            is_clean=not flagged,
            max_severity="red" if flagged else None,
            flag_count=1 if flagged else 0,
            red_count=1 if flagged else 0,
        )
        if flagged:
            arun_flagged.append(sub)

    add_sub(
        kobo_id="900",
        enumerator="Meena",
        calendar_day=OLDER_DAY,
        is_clean=True,
        duration=45.0,
    )
    add_sub(
        kobo_id="800",
        enumerator="Leak",
        calendar_day=DAY,
        is_clean=True,
        study_id=OTHER_STUDY,
        project_id="proj-other",
    )
    add_sub(
        kobo_id="700",
        enumerator="Orphan",
        calendar_day=DAY,
        is_clean=True,
        study_id=None,
        project_id="proj-orphan",
    )

    for idx, sub in enumerate(ravi_flagged):
        db.add(
            DqaFlag(
                id=f"flag-amber-{idx}",
                submission_id=sub.id,
                project_id="proj-golden",
                study_id=STUDY_ID,
                rule_id="skip_pattern",
                severity="amber",
                title="Skip pattern",
                message="skip",
            )
        )
    titles = ["GPS missing", "GPS drift", "Duration short"]
    rules = ["gps_missing", "gps_drift", "duration_short"]
    for idx, sub in enumerate(arun_flagged):
        db.add(
            DqaFlag(
                id=f"flag-red-{idx}",
                submission_id=sub.id,
                project_id="proj-golden",
                study_id=STUDY_ID,
                rule_id=rules[idx],
                severity="red",
                title=titles[idx],
                message="red",
            )
        )

    first = db.get(Submission, "proj-golden:100")
    assert first is not None
    db.add(
        SubmissionAnswer(
            id="ans-1",
            submission_id=first.id,
            project_id="proj-golden",
            study_id=STUDY_ID,
            field_key="q_age",
            field_label="Age",
            value_type="number",
            value_number=32.0,
        )
    )
    db.commit()
