"""add dqa_relationships table

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-09-02 23:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dqa_relationships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False, server_default=""),
        sa.Column("source_project_id", sa.String(), nullable=False),
        sa.Column("target_project_id", sa.String(), nullable=False),
        sa.Column("source_join_field", sa.String(), nullable=False),
        sa.Column("target_join_field", sa.String(), nullable=False),
        sa.Column("cardinality", sa.String(), nullable=False, server_default="one"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "code", name="dqa_relationships_study_code_uidx"),
    )
    op.create_index("dqa_relationships_study_idx", "dqa_relationships", ["study_id"])


def downgrade() -> None:
    op.drop_index("dqa_relationships_study_idx", table_name="dqa_relationships")
    op.drop_table("dqa_relationships")
