"""Base model for Report Specification types.

Kept independent of `app.schemas` so the spec stays a pure domain artifact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class SpecModel(BaseModel):
    """Camel-cased, strict model. Unknown keys are rejected so planner output cannot
    smuggle unsupported directives past validation."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
    )
