"""LOCAL-ONLY database reset: preserve settings, wipe everything else.

Never contacts KoboToolbox. Refuses to run unless:
  - ALLOW_LOCAL_DB_RESET=1 is set, and
  - DATABASE_PATH resolves under the repo's ./data directory (or an explicit
    INFOSUTRA_LOCAL_DB_ROOT override that you control).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import AppSettings  # noqa: F401 — register models
from app.db import models as _models  # noqa: F401
from app.services.studies import seed_default_study

logger = logging.getLogger(__name__)

# local_reset.py → services → app → api-python → artifacts → repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DATA_DIR = (_REPO_ROOT / "data").resolve()


def _assert_safe_local_path(db_path: Path) -> Path:
    if os.environ.get("ALLOW_LOCAL_DB_RESET", "").strip() != "1":
        raise RuntimeError(
            "Refusing to reset database: set ALLOW_LOCAL_DB_RESET=1 to confirm "
            "this is a local Infosutra SQLite wipe (Kobo is never contacted)."
        )

    resolved = db_path.resolve()
    allowed_roots: list[Path] = [_DEFAULT_DATA_DIR]
    override = os.environ.get("INFOSUTRA_LOCAL_DB_ROOT", "").strip()
    if override:
        allowed_roots.append(Path(override).resolve())

    if not any(
        resolved == root or root in resolved.parents or resolved.parent == root
        for root in allowed_roots
    ):
        raise RuntimeError(
            f"Refusing to reset database outside local data dir: {resolved}. "
            f"Allowed roots: {', '.join(str(r) for r in allowed_roots)}"
        )

    if resolved.suffix.lower() not in {".sqlite", ".db", ".sqlite3"}:
        raise RuntimeError(f"Refusing to reset non-sqlite path: {resolved}")

    return resolved


def _snapshot_settings(db: Session) -> dict[str, Any] | None:
    row = db.get(AppSettings, "singleton")
    if not row:
        return None
    data: dict[str, Any] = {}
    for column in AppSettings.__table__.columns:
        data[column.name] = getattr(row, column.name)
    return data


def _restore_settings(db: Session, snapshot: dict[str, Any] | None) -> None:
    if not snapshot:
        return
    row = AppSettings(id="singleton")
    for key, value in snapshot.items():
        if key == "id":
            continue
        if hasattr(row, key):
            setattr(row, key, value)
    db.merge(row)
    db.commit()


def reset_local_database(*, database_path: str | None = None) -> dict[str, Any]:
    """Wipe local SQLite (except settings), recreate schema, seed default study.

    Does not call Kobo or any remote API.
    """
    settings = get_settings()
    path = _assert_safe_local_path(Path(database_path or settings.database_path))

    # Snapshot settings from the live file if it exists.
    snapshot: dict[str, Any] | None = None
    if path.is_file():
        engine = create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            future=True,
        )
        SessionSnap = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
        with SessionSnap() as db:
            try:
                snapshot = _snapshot_settings(db)
            except Exception:
                logger.exception("Could not snapshot settings; continuing with empty settings")
                snapshot = None
        engine.dispose()

        # Remove SQLite sidecar files too.
        for sibling in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if sibling.is_file():
                sibling.unlink()
                logger.info("Removed %s", sibling)

    path.parent.mkdir(parents=True, exist_ok=True)
    from alembic import command
    from alembic.config import Config

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON"))
        conn.commit()
    engine.dispose()

    # Apply Alembic migrations to recreate schema
    api_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    # Temporarily point settings at this path for env.py
    previous = os.environ.get("DATABASE_PATH")
    os.environ["DATABASE_PATH"] = str(path)
    try:
        get_settings.cache_clear()
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = previous
        get_settings.cache_clear()

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionNew = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with SessionNew() as db:
        _restore_settings(db, snapshot)
        study = seed_default_study(db)
        study_id = study.id
        study_name = study.name

    engine.dispose()

    return {
        "database_path": str(path),
        "settings_preserved": snapshot is not None,
        "seeded_study_id": study_id,
        "seeded_study_name": study_name,
        "kobo_contacted": False,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    result = reset_local_database()
    print("Local DB reset complete (Kobo was NOT contacted):")
    for key, value in result.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
