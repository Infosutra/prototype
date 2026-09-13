"""reporting schema baseline + jobs platform

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-09-13 13:20:00.000000

Wipe-friendly Phase 0: add jobs/answers/quality, reshape report nullability,
drop ReportRun / is_system / generated_content / daily_report_* / study seed FKs.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": table},
    ).fetchall()
    return bool(rows)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def _has_index(name: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"),
        {"n": name},
    ).fetchall()
    return bool(rows)


def upgrade() -> None:
    # --- jobs ---
    if not _has_table("jobs"):
        op.create_table(
            "jobs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("study_id", sa.String(), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("result_ref", sa.String(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
        )
    if not _has_index("jobs_status_idx"):
        op.create_index("jobs_status_idx", "jobs", ["status"])
    if not _has_index("jobs_created_at_idx"):
        op.create_index("jobs_created_at_idx", "jobs", ["created_at"])

    # --- submission_answers ---
    if not _has_table("submission_answers"):
        op.create_table(
            "submission_answers",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("submission_id", sa.String(), sa.ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("study_id", sa.String(), nullable=False),
            sa.Column("field_key", sa.String(), nullable=False),
            sa.Column("field_label", sa.String(), nullable=True),
            sa.Column("value_type", sa.String(), nullable=False),
            sa.Column("value_text", sa.String(), nullable=True),
            sa.Column("value_number", sa.Float(), nullable=True),
            sa.Column("value_bool", sa.Boolean(), nullable=True),
            sa.Column("value_datetime", sa.DateTime(), nullable=True),
            sa.UniqueConstraint(
                "submission_id",
                "field_key",
                name="submission_answers_submission_field_uidx",
            ),
        )
    if not _has_index("submission_answers_study_field_idx"):
        op.create_index(
            "submission_answers_study_field_idx",
            "submission_answers",
            ["study_id", "field_key"],
        )
    if not _has_index("submission_answers_study_submission_idx"):
        op.create_index(
            "submission_answers_study_submission_idx",
            "submission_answers",
            ["study_id", "submission_id"],
        )

    # --- submission_quality ---
    if not _has_table("submission_quality"):
        op.create_table(
            "submission_quality",
            sa.Column(
                "submission_id",
                sa.String(),
                sa.ForeignKey("submissions.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("study_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), nullable=False),
            sa.Column("is_clean", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("max_severity", sa.String(), nullable=True),
            sa.Column("flag_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("red_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("amber_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    if not _has_index("submission_quality_study_idx"):
        op.create_index("submission_quality_study_idx", "submission_quality", ["study_id"])

    # --- submissions denorm columns ---
    with op.batch_alter_table("submissions") as batch_op:
        if not _has_column("submissions", "study_id"):
            batch_op.add_column(sa.Column("study_id", sa.String(), nullable=True))
        if not _has_column("submissions", "duration_minutes"):
            batch_op.add_column(sa.Column("duration_minutes", sa.Float(), nullable=True))
        if not _has_column("submissions", "calendar_day"):
            batch_op.add_column(sa.Column("calendar_day", sa.Date(), nullable=True))
    if not _has_index("submissions_study_calendar_day_idx"):
        op.create_index(
            "submissions_study_calendar_day_idx",
            "submissions",
            ["study_id", "calendar_day"],
        )

    # --- dqa_flags.study_id ---
    with op.batch_alter_table("dqa_flags") as batch_op:
        if not _has_column("dqa_flags", "study_id"):
            batch_op.add_column(sa.Column("study_id", sa.String(), nullable=True))
    if not _has_index("dqa_flags_study_idx"):
        op.create_index("dqa_flags_study_idx", "dqa_flags", ["study_id"])

    # --- reports: drop generated_content, add result_ref ---
    with op.batch_alter_table("reports") as batch_op:
        if not _has_column("reports", "result_ref"):
            batch_op.add_column(sa.Column("result_ref", sa.String(), nullable=True))
        if _has_column("reports", "generated_content"):
            batch_op.drop_column("generated_content")

    # --- drop report_runs ---
    if _has_table("report_runs"):
        if _has_index("report_runs_template_idx"):
            op.drop_index("report_runs_template_idx", table_name="report_runs")
        if _has_index("report_runs_created_idx"):
            op.drop_index("report_runs_created_idx", table_name="report_runs")
        op.drop_table("report_runs")

    # --- report_templates: drop is_system; study_id NOT NULL ---
    # Wipe orphan / unscoped templates before NOT NULL (prototype OK).
    if _has_table("report_templates"):
        op.execute(sa.text("DELETE FROM report_templates WHERE study_id IS NULL"))
        with op.batch_alter_table("report_templates") as batch_op:
            if _has_column("report_templates", "is_system"):
                batch_op.drop_column("is_system")
            # Recreate study_id as NOT NULL via batch (SQLite rebuild).
            batch_op.alter_column(
                "study_id",
                existing_type=sa.String(),
                nullable=False,
            )

    # --- report_schedules.template_id NOT NULL ---
    if _has_table("report_schedules"):
        op.execute(sa.text("DELETE FROM report_schedules WHERE template_id IS NULL"))
        with op.batch_alter_table("report_schedules") as batch_op:
            batch_op.alter_column(
                "template_id",
                existing_type=sa.String(),
                nullable=False,
            )

    # --- settings: drop daily_report_* ---
    daily_cols = [
        "daily_report_enabled",
        "daily_report_time",
        "daily_report_timezone",
        "daily_report_recipients",
        "daily_report_last_sent_on",
    ]
    with op.batch_alter_table("settings") as batch_op:
        for col in daily_cols:
            if _has_column("settings", col):
                batch_op.drop_column(col)

    # --- studies: drop seed template FK columns ---
    with op.batch_alter_table("studies") as batch_op:
        if _has_column("studies", "final_report_template_id"):
            batch_op.drop_column("final_report_template_id")
        if _has_column("studies", "daily_report_template_id"):
            batch_op.drop_column("daily_report_template_id")


def downgrade() -> None:
    # Prototype wipe — downgrade is best-effort restore of dropped columns only.
    with op.batch_alter_table("studies") as batch_op:
        if not _has_column("studies", "daily_report_template_id"):
            batch_op.add_column(sa.Column("daily_report_template_id", sa.String(), nullable=True))
        if not _has_column("studies", "final_report_template_id"):
            batch_op.add_column(sa.Column("final_report_template_id", sa.String(), nullable=True))

    with op.batch_alter_table("settings") as batch_op:
        if not _has_column("settings", "daily_report_enabled"):
            batch_op.add_column(
                sa.Column("daily_report_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
            )
        if not _has_column("settings", "daily_report_time"):
            batch_op.add_column(
                sa.Column("daily_report_time", sa.String(), nullable=False, server_default="21:00")
            )
        if not _has_column("settings", "daily_report_timezone"):
            batch_op.add_column(
                sa.Column(
                    "daily_report_timezone",
                    sa.String(),
                    nullable=False,
                    server_default="Asia/Kolkata",
                )
            )
        if not _has_column("settings", "daily_report_recipients"):
            batch_op.add_column(sa.Column("daily_report_recipients", sa.JSON(), nullable=False))
        if not _has_column("settings", "daily_report_last_sent_on"):
            batch_op.add_column(sa.Column("daily_report_last_sent_on", sa.String(), nullable=True))

    with op.batch_alter_table("report_schedules") as batch_op:
        batch_op.alter_column("template_id", existing_type=sa.String(), nullable=True)

    with op.batch_alter_table("report_templates") as batch_op:
        batch_op.alter_column("study_id", existing_type=sa.String(), nullable=True)
        if not _has_column("report_templates", "is_system"):
            batch_op.add_column(
                sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false())
            )

    if not _has_table("report_runs"):
        op.create_table(
            "report_runs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("study_id", sa.String(), nullable=True),
            sa.Column("template_id", sa.String(), nullable=True),
            sa.Column("template_version_id", sa.String(), nullable=True),
            sa.Column("conversation_id", sa.String(), nullable=True),
            sa.Column("report_id", sa.String(), nullable=True),
            sa.Column("provider", sa.String(), nullable=True),
            sa.Column("model", sa.String(), nullable=True),
            sa.Column("prompt_id", sa.String(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False),
            sa.Column("completion_tokens", sa.Integer(), nullable=False),
            sa.Column("latency_ms", sa.Float(), nullable=False),
            sa.Column("structured_output", sa.Boolean(), nullable=False),
            sa.Column("tool_calls_json", sa.JSON(), nullable=True),
            sa.Column("validation_errors_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    with op.batch_alter_table("reports") as batch_op:
        if not _has_column("reports", "generated_content"):
            batch_op.add_column(sa.Column("generated_content", sa.Text(), nullable=True))
        if _has_column("reports", "result_ref"):
            batch_op.drop_column("result_ref")

    if _has_index("dqa_flags_study_idx"):
        op.drop_index("dqa_flags_study_idx", table_name="dqa_flags")
    with op.batch_alter_table("dqa_flags") as batch_op:
        if _has_column("dqa_flags", "study_id"):
            batch_op.drop_column("study_id")

    if _has_index("submissions_study_calendar_day_idx"):
        op.drop_index("submissions_study_calendar_day_idx", table_name="submissions")
    with op.batch_alter_table("submissions") as batch_op:
        for col in ("calendar_day", "duration_minutes", "study_id"):
            if _has_column("submissions", col):
                batch_op.drop_column(col)

    if _has_table("submission_quality"):
        op.drop_table("submission_quality")
    if _has_table("submission_answers"):
        op.drop_table("submission_answers")
    if _has_table("jobs"):
        op.drop_table("jobs")
