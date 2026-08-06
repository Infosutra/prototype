"""Rule-pack loading, seeding, and persistence."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project, RulePack

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parent.parent / "rule_packs"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_seed_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    if not SEED_DIR.exists():
        return packs
    for path in sorted(SEED_DIR.glob("*.yml")) + sorted(SEED_DIR.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed reading seed pack %s", path)
            continue
        if isinstance(payload, dict):
            packs.append(payload)
    return packs


def get_pack_for_project(db: Session, project_id: str) -> dict[str, Any] | None:
    row = db.get(RulePack, project_id)
    if row and isinstance(row.pack, dict) and row.pack:
        return row.pack
    project = db.get(Project, project_id)
    uid = project.uid if project else project_id
    for seed in load_seed_packs():
        uids = seed.get("project_uids") or []
        if project_id in uids or uid in uids or seed.get("id") == project_id:
            return seed
    return None


def seed_rule_packs(db: Session, *, overwrite: bool = False) -> int:
    """Import YAML seeds into rule_packs for matching projects. Returns count written."""
    projects = {p.id: p for p in db.scalars(select(Project)).all()}
    by_uid = {p.uid: p for p in projects.values()}
    written = 0
    for seed in load_seed_packs():
        targets: list[Project] = []
        for uid in seed.get("project_uids") or []:
            if uid in projects:
                targets.append(projects[uid])
            elif uid in by_uid:
                targets.append(by_uid[uid])
        for project in targets:
            existing = db.get(RulePack, project.id)
            if existing and not overwrite:
                continue
            if existing:
                existing.pack = seed
                existing.updated_at = _now()
            else:
                db.add(RulePack(project_id=project.id, pack=seed, updated_at=_now()))
            written += 1
    if written:
        db.commit()
    return written


def save_pack(db: Session, project_id: str, pack: dict[str, Any]) -> dict[str, Any]:
    row = db.get(RulePack, project_id)
    if row:
        row.pack = pack
        row.updated_at = _now()
    else:
        row = RulePack(project_id=project_id, pack=pack, updated_at=_now())
        db.add(row)
    db.commit()
    db.refresh(row)
    return row.pack
