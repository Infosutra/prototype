"""Lightweight SQLite column adds for evolving local schema.

create_all does not ALTER existing tables — call ensure_schema() after init_db().
Never contacts Kobo.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# (table, column, sqlite_type_with_optional_default)
_COLUMNS: list[tuple[str, str, str]] = [
    ("settings", "ai_base_url", "VARCHAR DEFAULT 'https://openrouter.ai/api/v1'"),
    ("settings", "ai_model", "VARCHAR DEFAULT 'nvidia/nemotron-3-super-120b-a12b:free'"),
    ("settings", "ai_temperature", "FLOAT DEFAULT 0.3"),
    ("settings", "ai_max_tokens", "INTEGER DEFAULT 2048"),
    ("settings", "ai_timeout_seconds", "INTEGER DEFAULT 60"),
    ("settings", "dqa_daily_enabled", "BOOLEAN DEFAULT 0"),
    ("settings", "dqa_daily_time", "VARCHAR DEFAULT '21:30'"),
    ("settings", "dqa_daily_timezone", "VARCHAR DEFAULT 'Asia/Kolkata'"),
    ("settings", "dqa_daily_recipients", "JSON DEFAULT '[]'"),
    ("settings", "dqa_daily_last_sent_on", "VARCHAR"),
    ("settings", "dqa_daily_study_id", "VARCHAR"),
    ("reports", "report_type", "VARCHAR DEFAULT 'custom'"),
    ("reports", "study_id", "VARCHAR"),
    ("reports", "report_date", "VARCHAR"),
]


def ensure_schema(engine: Engine) -> int:
    added = 0
    with engine.begin() as conn:
        for table, column, col_def in _COLUMNS:
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            if not rows:
                continue
            existing = {row[1] for row in rows}
            if column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
            added += 1
            logger.info("Added column %s.%s", table, column)
    return added
