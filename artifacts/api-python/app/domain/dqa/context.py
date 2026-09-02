"""Evaluation context for DQA check evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationContext:
    """Inputs available while evaluating one rule against one primary submission.

    Phase 0 resolves field values from ``data`` + ``pack`` only. Phase 2 may
    populate ``related`` / ``related_packs`` after relationship resolution; those
    slots are not used in Phase 0.
    """

    data: dict[str, Any]
    pack: dict[str, Any]
    current: Any | None = None
    project_rows: list[Any] | None = None

    @classmethod
    def from_eval_args(
        cls,
        *,
        data: dict[str, Any],
        pack: dict[str, Any],
        project_rows: list[Any] | None = None,
        current: Any | None = None,
    ) -> EvaluationContext:
        return cls(
            data=data,
            pack=pack,
            current=current,
            project_rows=project_rows or None,
        )
