"""working spec and authoring JSON on report templates

Revision ID: b8c9d0e1f2a3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-14 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    if not _has_column("report_templates", "working_spec_json"):
        op.add_column(
            "report_templates",
            sa.Column("working_spec_json", sa.JSON(), nullable=True),
        )
    if not _has_column("report_templates", "authoring_json"):
        op.add_column(
            "report_templates",
            sa.Column("authoring_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _has_column("report_templates", "authoring_json"):
        op.drop_column("report_templates", "authoring_json")
    if _has_column("report_templates", "working_spec_json"):
        op.drop_column("report_templates", "working_spec_json")
