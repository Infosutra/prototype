"""move transcripts to disk and drop json columns

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-15 11:35:00.000000

"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _migrate_row(
    *,
    recording_id: str,
    storage_path: str,
    transcript: dict | None,
    transcript_raw: dict | None,
) -> str | None:
    from app.services.audio_storage import (
        SOURCE_BASENAME,
        recording_dir,
        reports_dir,
        transcript_path,
        transcript_raw_path,
    )

    folder = recording_dir(recording_id)
    reports_dir(recording_id)

    new_storage_path: str | None = None
    old_path = Path(storage_path) if storage_path else None
    if old_path and old_path.is_file() and old_path.parent.resolve() != folder.resolve():
        ext = old_path.suffix or ".mp3"
        target = folder / f"{SOURCE_BASENAME}{ext}"
        if not target.exists():
            shutil.move(str(old_path), str(target))
        new_storage_path = str(target)

    if transcript:
        transcript_path(recording_id).write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if transcript_raw:
        transcript_raw_path(recording_id).write_text(
            json.dumps(transcript_raw, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return new_storage_path


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, storage_path, transcript, transcript_raw FROM audio_recordings"
        )
    ).mappings()

    for row in rows:
        transcript = row["transcript"]
        if isinstance(transcript, str):
            transcript = json.loads(transcript)
        transcript_raw = row["transcript_raw"]
        if isinstance(transcript_raw, str):
            transcript_raw = json.loads(transcript_raw)

        new_storage_path = _migrate_row(
            recording_id=row["id"],
            storage_path=row["storage_path"] or "",
            transcript=transcript if isinstance(transcript, dict) else None,
            transcript_raw=transcript_raw if isinstance(transcript_raw, dict) else None,
        )
        if new_storage_path:
            connection.execute(
                sa.text(
                    "UPDATE audio_recordings SET storage_path = :storage_path WHERE id = :id"
                ),
                {"storage_path": new_storage_path, "id": row["id"]},
            )

    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.drop_column("transcript_raw")
        batch_op.drop_column("transcript")


def downgrade() -> None:
    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("transcript", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("transcript_raw", sa.JSON(), nullable=True))
