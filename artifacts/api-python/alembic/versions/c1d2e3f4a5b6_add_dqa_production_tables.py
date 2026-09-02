"""add dqa production tables (compile sessions, rule pack versions)

Revision ID: c1d2e3f4a5b6
Revises: b0c1d2e3f4a5
Create Date: 2026-09-02 23:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rule_packs",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "rule_pack_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pack", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("compile_session_id", sa.String(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "version", name="rule_pack_versions_project_version_uidx"),
    )
    op.create_index("rule_pack_versions_project_idx", "rule_pack_versions", ["project_id"])

    op.create_table(
        "dqa_compile_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("english", sa.Text(), nullable=False, server_default=""),
        sa.Column("conversation_turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("model", sa.String(), nullable=False, server_default=""),
        sa.Column("prompt_id", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_valid", sa.Integer(), nullable=True),
        sa.Column("validation_errors", sa.JSON(), nullable=True),
        sa.Column("rule_id", sa.String(), nullable=True),
        sa.Column("rule_snapshot", sa.JSON(), nullable=True),
        sa.Column("preview_summary", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("dqa_compile_sessions_project_idx", "dqa_compile_sessions", ["project_id"])
    op.create_index("dqa_compile_sessions_status_idx", "dqa_compile_sessions", ["status"])


def downgrade() -> None:
    op.drop_index("dqa_compile_sessions_status_idx", table_name="dqa_compile_sessions")
    op.drop_index("dqa_compile_sessions_project_idx", table_name="dqa_compile_sessions")
    op.drop_table("dqa_compile_sessions")
    op.drop_index("rule_pack_versions_project_idx", table_name="rule_pack_versions")
    op.drop_table("rule_pack_versions")
    op.drop_column("rule_packs", "version")
