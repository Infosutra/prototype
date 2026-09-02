"""add audio transcription and usage events

Revision ID: d6e7f8a9b0c1
Revises: c5b2d3e4f5a6
Create Date: 2026-08-15 10:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5b2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audio_recordings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("study_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("original_filename", sa.String(), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(), nullable=False, server_default=""),
        sa.Column("storage_path", sa.String(), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("transcription_status", sa.String(), nullable=False, server_default="none"),
        sa.Column("transcription_provider", sa.String(), nullable=True),
        sa.Column("transcription_language", sa.String(), nullable=True),
        sa.Column("transcription_error", sa.Text(), nullable=True),
        sa.Column("transcription_job_ref", sa.Text(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("transcript_raw", sa.JSON(), nullable=True),
        sa.Column("transcribed_at", sa.DateTime(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.create_index("audio_recordings_study_idx", ["study_id"], unique=False)
        batch_op.create_index("audio_recordings_status_idx", ["transcription_status"], unique=False)

    op.create_table(
        "usage_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default=""),
        sa.Column("operation", sa.String(), nullable=False, server_default=""),
        sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(), nullable=False, server_default=""),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(), nullable=False, server_default="INR"),
        sa.Column("study_id", sa.String(), nullable=True),
        sa.Column("resource_type", sa.String(), nullable=True),
        sa.Column("resource_id", sa.String(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["study_id"], ["studies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.create_index("usage_events_category_idx", ["category"], unique=False)
        batch_op.create_index("usage_events_study_idx", ["study_id"], unique=False)
        batch_op.create_index("usage_events_occurred_idx", ["occurred_at"], unique=False)

    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("transcription_enabled", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column(
                "transcription_provider",
                sa.String(),
                nullable=False,
                server_default="sarvam",
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcription_api_key_encrypted",
                sa.Text(),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcription_base_url",
                sa.String(),
                nullable=False,
                server_default="https://api.sarvam.ai",
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcription_model",
                sa.String(),
                nullable=False,
                server_default="saaras-v3",
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcription_currency",
                sa.String(),
                nullable=False,
                server_default="INR",
            )
        )
        batch_op.add_column(
            sa.Column(
                "transcription_rate_per_minute",
                sa.Float(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.drop_column("transcription_rate_per_minute")
        batch_op.drop_column("transcription_currency")
        batch_op.drop_column("transcription_model")
        batch_op.drop_column("transcription_base_url")
        batch_op.drop_column("transcription_api_key_encrypted")
        batch_op.drop_column("transcription_provider")
        batch_op.drop_column("transcription_enabled")

    with op.batch_alter_table("usage_events", schema=None) as batch_op:
        batch_op.drop_index("usage_events_occurred_idx")
        batch_op.drop_index("usage_events_study_idx")
        batch_op.drop_index("usage_events_category_idx")
    op.drop_table("usage_events")

    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.drop_index("audio_recordings_status_idx")
        batch_op.drop_index("audio_recordings_study_idx")
    op.drop_table("audio_recordings")
