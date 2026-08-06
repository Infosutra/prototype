"""add triangulation_views

Revision ID: b4a1c2d3e4f5
Revises: 082fb2cb4010
Create Date: 2026-08-06 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b4a1c2d3e4f5"
down_revision: Union[str, Sequence[str], None] = "082fb2cb4010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "triangulation_views",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("study_id", "code", name="triangulation_views_study_code_uidx"),
    )
    op.create_index(
        "triangulation_views_study_idx",
        "triangulation_views",
        ["study_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("triangulation_views_study_idx", table_name="triangulation_views")
    op.drop_table("triangulation_views")
