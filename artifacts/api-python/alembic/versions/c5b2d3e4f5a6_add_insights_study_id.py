"""add insights.study_id

Revision ID: c5b2d3e4f5a6
Revises: b4a1c2d3e4f5
Create Date: 2026-08-06 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c5b2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "b4a1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("insights") as batch_op:
        batch_op.add_column(sa.Column("study_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "insights_study_id_fkey",
            "studies",
            ["study_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("insights_study_idx", ["study_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("insights") as batch_op:
        batch_op.drop_index("insights_study_idx")
        batch_op.drop_constraint("insights_study_id_fkey", type_="foreignkey")
        batch_op.drop_column("study_id")
