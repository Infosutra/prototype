"""System prompt ids for Prompts UI (compile + reporting planner/analyst).

No Daily/Final report narrative seed prompts — users author report templates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import Prompt
from app.services.dqa_compile_prompt import (
    DEFAULT_DQA_COMPILE_PROMPT,
    DQA_COMPILE_CATEGORY,
    DQA_COMPILE_PROMPT_ID,
)
from app.services.reporting.prompt_seeds import (
    REPORTING_SYSTEM_PROMPT_IDS,
    reporting_prompt_seed,
)

SYSTEM_PROMPT_IDS = frozenset(
    {
        DQA_COMPILE_PROMPT_ID,
        *REPORTING_SYSTEM_PROMPT_IDS,
    }
)


def system_prompt_seed(prompt_id: str) -> tuple[str, str, str, str] | None:
    """Return (name, description, content, category) for a seeded system prompt."""
    reporting = reporting_prompt_seed(prompt_id)
    if reporting is not None:
        return reporting
    if prompt_id == DQA_COMPILE_PROMPT_ID:
        return (
            "DQA rule compiler",
            "System instructions for compiling English DQA rules to JSON checks",
            DEFAULT_DQA_COMPILE_PROMPT,
            DQA_COMPILE_CATEGORY,
        )
    return None


def revert_system_prompt(db: Session, prompt_id: str) -> Prompt:
    """Restore a seeded system prompt to its packaged DEFAULT content."""
    seed = system_prompt_seed(prompt_id)
    if seed is None or prompt_id not in SYSTEM_PROMPT_IDS:
        raise ValueError("Only seeded system prompts can be reverted to the original version.")
    name, description, content, category = seed
    row = db.get(Prompt, prompt_id)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if row is None:
        row = Prompt(
            id=prompt_id,
            name=name,
            description=description,
            content=content,
            category=category,
            project_ids=[],
            created_at=now,
            updated_at=now,
        )
        db.add(row)
    else:
        row.name = name
        row.description = description
        row.content = content
        row.category = category
        row.updated_at = now
    db.commit()
    db.refresh(row)
    return row
