"""point report schedules at templates

Revision ID: f5a6b7c8d9e0
Revises: e3f4a5b6c7d8
Create Date: 2026-09-05 17:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    # SQLite cannot reliably add a named FK after table creation without a full
    # table rebuild. The column is enough for the ORM relationship; referential
    # cleanup is handled in application code.
    if not _has_column("report_schedules", "template_id"):
        op.add_column(
            "report_schedules",
            sa.Column("template_id", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("report_schedules", "template_id"):
        op.drop_column("report_schedules", "template_id")
