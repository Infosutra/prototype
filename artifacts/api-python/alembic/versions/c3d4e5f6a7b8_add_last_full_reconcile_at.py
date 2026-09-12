"""add projects.last_full_reconcile_at

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-11 20:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("projects", "last_full_reconcile_at"):
        op.add_column(
            "projects",
            sa.Column("last_full_reconcile_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("projects", "last_full_reconcile_at"):
        op.drop_column("projects", "last_full_reconcile_at")
