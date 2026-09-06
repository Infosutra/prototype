"""default execution date on report templates

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-09-05 19:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("report_templates", "default_execution_date"):
        op.add_column(
            "report_templates",
            sa.Column("default_execution_date", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("report_templates", "default_execution_date"):
        op.drop_column("report_templates", "default_execution_date")
