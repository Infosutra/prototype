"""report templates, versions, conversations, runs and spec columns

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-05 16:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "report_templates",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("study_id", sa.String(), nullable=True),
        sa.Column("report_kind", sa.String(), nullable=False, server_default="adhoc"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("current_version_id", sa.String(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("report_templates_study_idx", "report_templates", ["study_id"])
    op.create_index("report_templates_kind_idx", "report_templates", ["report_kind"])

    op.create_table(
        "report_template_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("template_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("spec_version", sa.String(), nullable=False, server_default="1.0"),
        sa.Column("planner_model", sa.String(), nullable=True),
        sa.Column("planner_prompt_id", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="template"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["template_id"], ["report_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version", name="report_template_versions_uidx"),
    )
    op.create_index(
        "report_template_versions_template_idx", "report_template_versions", ["template_id"]
    )

    op.create_table(
        "report_conversations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default="Untitled report"),
        sa.Column("working_spec_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("saved_template_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("report_conversations_study_idx", "report_conversations", ["study_id"])

    op.create_table(
        "report_conversation_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("spec_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("changes_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["report_conversations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "report_conversation_messages_conv_idx",
        "report_conversation_messages",
        ["conversation_id"],
    )

    op.create_table(
        "report_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=True),
        sa.Column("template_id", sa.String(), nullable=True),
        sa.Column("template_version_id", sa.String(), nullable=True),
        sa.Column("conversation_id", sa.String(), nullable=True),
        sa.Column("report_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_id", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("structured_output", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tool_calls_json", sa.JSON(), nullable=True),
        sa.Column("validation_errors_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("report_runs_created_idx", "report_runs", ["created_at"])
    op.create_index("report_runs_template_idx", "report_runs", ["template_id"])

    with op.batch_alter_table("reports") as batch_op:
        batch_op.add_column(sa.Column("template_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("template_version_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("spec_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("execution_context_json", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "reports_template_id_fkey",
            "report_templates",
            ["template_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "reports_template_version_id_fkey",
            "report_template_versions",
            ["template_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("studies") as batch_op:
        batch_op.add_column(sa.Column("daily_report_template_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("final_report_template_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "studies_daily_report_template_id_fkey",
            "report_templates",
            ["daily_report_template_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "studies_final_report_template_id_fkey",
            "report_templates",
            ["final_report_template_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("studies") as batch_op:
        batch_op.drop_constraint("studies_final_report_template_id_fkey", type_="foreignkey")
        batch_op.drop_constraint("studies_daily_report_template_id_fkey", type_="foreignkey")
        batch_op.drop_column("final_report_template_id")
        batch_op.drop_column("daily_report_template_id")

    with op.batch_alter_table("reports") as batch_op:
        batch_op.drop_constraint("reports_template_version_id_fkey", type_="foreignkey")
        batch_op.drop_constraint("reports_template_id_fkey", type_="foreignkey")
        batch_op.drop_column("execution_context_json")
        batch_op.drop_column("spec_json")
        batch_op.drop_column("template_version_id")
        batch_op.drop_column("template_id")

    op.drop_index("report_runs_template_idx", table_name="report_runs")
    op.drop_index("report_runs_created_idx", table_name="report_runs")
    op.drop_table("report_runs")
    op.drop_index(
        "report_conversation_messages_conv_idx", table_name="report_conversation_messages"
    )
    op.drop_table("report_conversation_messages")
    op.drop_index("report_conversations_study_idx", table_name="report_conversations")
    op.drop_table("report_conversations")
    op.drop_index(
        "report_template_versions_template_idx", table_name="report_template_versions"
    )
    op.drop_table("report_template_versions")
    op.drop_index("report_templates_kind_idx", table_name="report_templates")
    op.drop_index("report_templates_study_idx", table_name="report_templates")
    op.drop_table("report_templates")
