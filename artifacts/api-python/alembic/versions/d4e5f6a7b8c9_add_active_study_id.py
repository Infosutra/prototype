"""add settings.active_study_id

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-12 10:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("settings", "active_study_id"):
        op.add_column(
            "settings",
            sa.Column("active_study_id", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("settings", "active_study_id"):
        op.drop_column("settings", "active_study_id")
