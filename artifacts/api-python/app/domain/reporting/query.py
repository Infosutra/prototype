"""Query IR models for the reporting query engine."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.time_window import WINDOW_PRESETS, WindowPreset
from app.schemas.common import to_camel

EntityName = Literal["submission", "flag", "answer"]
MeasureFn = Literal["count", "countDistinct", "countWhere", "sum", "avg", "min", "max"]
FilterOp = Literal["eq", "neq", "in", "isTrue", "isFalse", "gt", "gte", "lt", "lte"]
SortDir = Literal["asc", "desc"]


class _ForbidCamel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Measure(_ForbidCamel):
    id: str
    fn: MeasureFn
    field: str | None = None
    eq: bool | str | int | float | None = None

    @model_validator(mode="after")
    def _field_rules(self) -> Measure:
        if self.fn == "count":
            return self
        if self.fn == "countWhere":
            if not self.field:
                raise ValueError("countWhere requires field")
            if self.eq is None:
                raise ValueError("countWhere requires eq")
            return self
        if not self.field:
            raise ValueError(f"{self.fn} requires field")
        return self


class Filter(_ForbidCamel):
    field: str
    op: FilterOp
    value: Any = None

    @model_validator(mode="after")
    def _value_rules(self) -> Filter:
        if self.op in {"isTrue", "isFalse"}:
            return self
        if self.op == "in":
            if not isinstance(self.value, list) or len(self.value) == 0:
                raise ValueError("in filter requires a non-empty list value")
            return self
        if self.value is None:
            raise ValueError(f"Filter op '{self.op}' requires value")
        return self


class Sort(_ForbidCamel):
    field: str
    dir: SortDir = "asc"


class Query(_ForbidCamel):
    entity: EntityName
    window: WindowPreset
    group_by: list[str] = Field(default_factory=list)
    measures: list[Measure] | None = None
    filters: list[Filter] = Field(default_factory=list)
    limit: int | None = None
    sort: Sort | None = None

    @model_validator(mode="after")
    def _window_ok(self) -> Query:
        if self.window not in WINDOW_PRESETS:
            raise ValueError(f"Unknown window preset '{self.window}'")
        return self
