"""add study daily/final DQA prompt FKs

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-03 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("studies") as batch_op:
        batch_op.add_column(sa.Column("daily_dqa_prompt_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("final_dqa_prompt_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "studies_daily_dqa_prompt_id_fkey",
            "prompts",
            ["daily_dqa_prompt_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "studies_final_dqa_prompt_id_fkey",
            "prompts",
            ["final_dqa_prompt_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("studies_daily_dqa_prompt_idx", ["daily_dqa_prompt_id"], unique=False)
        batch_op.create_index("studies_final_dqa_prompt_idx", ["final_dqa_prompt_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("studies") as batch_op:
        batch_op.drop_index("studies_final_dqa_prompt_idx")
        batch_op.drop_index("studies_daily_dqa_prompt_idx")
        batch_op.drop_constraint("studies_final_dqa_prompt_id_fkey", type_="foreignkey")
        batch_op.drop_constraint("studies_daily_dqa_prompt_id_fkey", type_="foreignkey")
        batch_op.drop_column("final_dqa_prompt_id")
        batch_op.drop_column("daily_dqa_prompt_id")
