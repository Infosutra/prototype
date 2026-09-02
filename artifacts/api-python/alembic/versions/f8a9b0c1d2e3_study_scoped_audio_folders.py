"""study-scoped audio folders and unique recording names

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-08-15 12:00:00.000000

"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _migrate_recording(
    *,
    recording_id: str,
    study_id: str,
    study_name: str,
    recording_name: str,
    storage_path: str,
) -> tuple[str, str, str]:
    from app.services.audio_storage import (
        SOURCE_BASENAME,
        audio_dir,
        build_storage_folder,
        ensure_recording_layout,
        normalize_recording_name,
    )

    storage_folder = build_storage_folder(
        study_name=study_name,
        study_id=study_id,
        recording_name=recording_name,
    )
    name_normalized = normalize_recording_name(recording_name)

    old_path = Path(storage_path) if storage_path else None
    new_dir = ensure_recording_layout(storage_folder)
    new_storage_path = str(new_dir / f"{SOURCE_BASENAME}.mp3")

    if old_path and old_path.is_file():
        ext = old_path.suffix or ".mp3"
        target = new_dir / f"{SOURCE_BASENAME}{ext}"
        if not target.exists():
            shutil.move(str(old_path), str(target))
        new_storage_path = str(target)

    legacy_dir = audio_dir() / recording_id
    if legacy_dir.is_dir() and legacy_dir.resolve() != new_dir.resolve():
        for child in legacy_dir.iterdir():
            target = new_dir / child.name
            if child.is_dir():
                if not target.exists():
                    shutil.move(str(child), str(target))
                continue
            if not target.exists():
                shutil.move(str(child), str(target))
        try:
            if not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()
        except OSError:
            pass

    if not Path(new_storage_path).is_file():
        candidates = list(new_dir.glob(f"{SOURCE_BASENAME}.*"))
        if candidates:
            new_storage_path = str(candidates[0])

    return storage_folder, name_normalized, new_storage_path


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT ar.id, ar.study_id, ar.name, ar.storage_path, s.name AS study_name
            FROM audio_recordings ar
            JOIN studies s ON s.id = ar.study_id
            """
        )
    ).mappings()

    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("storage_folder", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("name_normalized", sa.String(), nullable=True))

    for row in rows:
        storage_folder, name_normalized, storage_path = _migrate_recording(
            recording_id=row["id"],
            study_id=row["study_id"],
            study_name=row["study_name"] or row["study_id"],
            recording_name=row["name"] or "recording",
            storage_path=row["storage_path"] or "",
        )
        connection.execute(
            sa.text(
                """
                UPDATE audio_recordings
                SET storage_folder = :storage_folder,
                    name_normalized = :name_normalized,
                    storage_path = :storage_path
                WHERE id = :id
                """
            ),
            {
                "storage_folder": storage_folder,
                "name_normalized": name_normalized,
                "storage_path": storage_path,
                "id": row["id"],
            },
        )

    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.alter_column("storage_folder", nullable=False)
        batch_op.alter_column("name_normalized", nullable=False)
        batch_op.create_unique_constraint(
            "audio_recordings_study_name_uidx",
            ["study_id", "name_normalized"],
        )


def downgrade() -> None:
    with op.batch_alter_table("audio_recordings", schema=None) as batch_op:
        batch_op.drop_constraint("audio_recordings_study_name_uidx", type_="unique")
        batch_op.drop_column("name_normalized")
        batch_op.drop_column("storage_folder")
