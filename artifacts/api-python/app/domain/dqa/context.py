"""Evaluation context for DQA check evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RelatedResolution:
    """Result of resolving one relationship for the current submission."""

    relationship_code: str
    status: str  # resolved | none | ambiguous | missing_key
    submission: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)
    pack: dict[str, Any] = field(default_factory=dict)
    join_key: str | None = None
    candidates: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class EvaluationContext:
    """Inputs available while evaluating one rule against one primary submission."""

    data: dict[str, Any]
    pack: dict[str, Any]
    current: Any | None = None
    project_rows: list[Any] | None = None
    related: dict[str, RelatedResolution] = field(default_factory=dict)
    study_id: str | None = None

    @classmethod
    def from_eval_args(
        cls,
        *,
        data: dict[str, Any],
        pack: dict[str, Any],
        project_rows: list[Any] | None = None,
        current: Any | None = None,
        related: dict[str, RelatedResolution] | None = None,
        study_id: str | None = None,
    ) -> EvaluationContext:
        return cls(
            data=data,
            pack=pack,
            current=current,
            project_rows=project_rows or None,
            related=dict(related or {}),
            study_id=study_id,
        )
