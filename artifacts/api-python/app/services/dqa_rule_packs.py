"""Rule-pack loading, seeding, versioning, and persistence."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Project, RulePack, RulePackVersion
from app.domain.dqa.rule_audit import stamp_rules_for_save

logger = logging.getLogger(__name__)

SEED_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent / "rule_packs"
MAX_RULES_PER_PACK = 256
MAX_PACK_JSON_BYTES = 512_000


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _validate_pack_size(pack: dict[str, Any]) -> None:
    rules = pack.get("rules")
    if isinstance(rules, list) and len(rules) > MAX_RULES_PER_PACK:
        raise ValueError(f"Rule pack exceeds {MAX_RULES_PER_PACK} rules")
    import json

    encoded = json.dumps(pack, ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_PACK_JSON_BYTES:
        raise ValueError("Rule pack JSON exceeds size limit")


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


def get_pack_version(db: Session, project_id: str) -> int:
    row = db.get(RulePack, project_id)
    if row and getattr(row, "version", None):
        return int(row.version)
    return 0


def list_pack_versions(db: Session, project_id: str, *, limit: int = 50) -> list[RulePackVersion]:
    limit = max(1, min(int(limit or 50), 200))
    return list(
        db.scalars(
            select(RulePackVersion)
            .where(RulePackVersion.project_id == project_id)
            .order_by(RulePackVersion.version.desc())
            .limit(limit)
        ).all()
    )


def get_pack_version_by_number(
    db: Session, project_id: str, version: int
) -> RulePackVersion | None:
    return db.scalars(
        select(RulePackVersion).where(
            RulePackVersion.project_id == project_id,
            RulePackVersion.version == version,
        )
    ).first()


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
            save_pack(db, project.id, seed, source="seed", change_note="seed import")
            written += 1
    return written


def save_pack(
    db: Session,
    project_id: str,
    pack: dict[str, Any],
    *,
    source: str = "manual",
    change_note: str | None = None,
    compile_session_id: str | None = None,
) -> dict[str, Any]:
    _validate_pack_size(pack)
    row = db.get(RulePack, project_id)
    previous_rules = {}
    if row and isinstance(row.pack, dict):
        for item in row.pack.get("rules") or []:
            if isinstance(item, dict) and item.get("id"):
                previous_rules[str(item["id"])] = item

    next_version = int(getattr(row, "version", 0) or 0) + 1 if row else 1
    rules = pack.get("rules") if isinstance(pack.get("rules"), list) else []
    stamped_rules = stamp_rules_for_save(rules, pack_version=next_version, previous_rules=previous_rules)
    stored = dict(pack)
    stored["rules"] = stamped_rules
    stored["pack_version"] = next_version

    db.execute(
        update(RulePackVersion)
        .where(
            RulePackVersion.project_id == project_id,
            RulePackVersion.status == "active",
        )
        .values(status="superseded")
    )
    version_row = RulePackVersion(
        id=str(uuid.uuid4()),
        project_id=project_id,
        version=next_version,
        pack=stored,
        status="active",
        source=source,
        compile_session_id=compile_session_id,
        change_note=change_note,
    )
    db.add(version_row)

    if row:
        row.pack = stored
        row.version = next_version
        row.updated_at = _now()
    else:
        row = RulePack(project_id=project_id, pack=stored, version=next_version, updated_at=_now())
        db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "Saved rule pack project_id=%s version=%s source=%s rules=%s",
        project_id,
        next_version,
        source,
        len(stamped_rules),
    )
    return row.pack
