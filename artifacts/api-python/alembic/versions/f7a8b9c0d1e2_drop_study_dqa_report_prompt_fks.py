"""drop unused study daily/final dqa prompt FKs

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-13 15:25:00.000000

Cleanup C2: remove orphan Daily/Final report-prompt assignment columns.
Schedules still use template_id; report-planner/analyst prompts remain.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    with op.batch_alter_table("studies") as batch_op:
        if _has_index("studies_final_dqa_prompt_idx"):
            batch_op.drop_index("studies_final_dqa_prompt_idx")
        if _has_index("studies_daily_dqa_prompt_idx"):
            batch_op.drop_index("studies_daily_dqa_prompt_idx")
        # SQLite batch mode recreates the table; drop FKs by dropping columns.
        if _has_column("studies", "final_dqa_prompt_id"):
            batch_op.drop_column("final_dqa_prompt_id")
        if _has_column("studies", "daily_dqa_prompt_id"):
            batch_op.drop_column("daily_dqa_prompt_id")


def downgrade() -> None:
    with op.batch_alter_table("studies") as batch_op:
        if not _has_column("studies", "daily_dqa_prompt_id"):
            batch_op.add_column(sa.Column("daily_dqa_prompt_id", sa.String(), nullable=True))
        if not _has_column("studies", "final_dqa_prompt_id"):
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
        if not _has_index("studies_daily_dqa_prompt_idx"):
            batch_op.create_index("studies_daily_dqa_prompt_idx", ["daily_dqa_prompt_id"])
        if not _has_index("studies_final_dqa_prompt_idx"):
            batch_op.create_index("studies_final_dqa_prompt_idx", ["final_dqa_prompt_id"])
