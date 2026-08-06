from __future__ import annotations

from typing import Any

from app.schemas.common import CamelModel


class FormFieldOut(CamelModel):
    name: str
    type: str
    label: str
    list_name: str | None = None
    choices: list[dict[str, Any]] = []


class RulePackOut(CamelModel):
    project_id: str
    pack: dict[str, Any]


class RulePackUpdate(CamelModel):
    pack: dict[str, Any]


class DqaFlagOut(CamelModel):
    id: str
    submission_id: str
    project_id: str
    rule_id: str
    severity: str
    title: str
    message: str
    details: dict[str, Any] | None = None
    evaluated_at: str
    enumerator: str | None = None
    project_name: str | None = None
    kobo_id: str | None = None
    submitted_at: str | None = None


class DqaRuleCount(CamelModel):
    rule_id: str
    title: str
    severity: str
    count: int


class DqaSummary(CamelModel):
    project_id: str | None = None
    total_submissions: int
    flagged_submissions: int
    flagged_pct: float
    red_flags: int
    amber_flags: int
    by_rule: list[DqaRuleCount]


class ProjectDqaStat(CamelModel):
    project_id: str
    project_name: str
    total_submissions: int
    clean_submissions: int
    amber_submissions: int
    red_submissions: int
    red_flags: int
    amber_flags: int
    flagged_pct: float


class DqaRecomputeResult(CamelModel):
    project_id: str | None = None
    submissions: int
    flagged_submissions: int
    flags: int


class EnumeratorStat(CamelModel):
    enumerator: str
    submissions: int
    flagged: int
    flagged_pct: float
    red_flags: int
    amber_flags: int = 0
    median_duration_minutes: float | None = None


class TriangulationLink(CamelModel):
    submission_id: str | None = None
    kobo_id: str | None = None
    enumerator: str | None = None
    submitted_at: str | None = None
    project_name: str | None = None


class TriangulationPracticeStat(CamelModel):
    id: str
    label: str
    claimed_count: int = 0
    observed_count: int = 0
    n: int = 0
    claimed_pct: float = 0.0
    observed_pct: float = 0.0
    concordance_pct: float = 0.0
    gap_pct: float = 0.0


class TriangulationColumn(CamelModel):
    key: str
    label: str
    kind: str = "text"  # text | bool | number | list


class TriangulationCell(CamelModel):
    key: str
    label: str
    value: Any = None
    kind: str = "text"  # text | bool | number | list


class TriangulationRow(CamelModel):
    key: str
    cells: list[TriangulationCell] = []
    links: dict[str, TriangulationLink | None] = {}
    mismatch: bool = False


class TriangulationViewOut(CamelModel):
    id: str
    title: str
    description: str | None = None
    columns: list[TriangulationColumn] = []
    rows: list[TriangulationRow]
    mismatch_count: int
    practices: list[TriangulationPracticeStat] = []


class TriangulationViewInfo(CamelModel):
    id: str
    title: str


class TriangulationViewDefinitionOut(CamelModel):
    id: str
    study_id: str
    code: str
    title: str
    description: str | None = None
    definition: dict[str, Any]


class TriangulationViewDefinitionUpdate(CamelModel):
    title: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    code: str | None = None


class TriangulationViewDefinitionCreate(CamelModel):
    code: str
    title: str
    description: str | None = None
    definition: dict[str, Any]