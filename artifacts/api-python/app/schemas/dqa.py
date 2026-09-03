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
    version: int = 1


class RulePackVersionOut(CamelModel):
    id: str
    project_id: str
    version: int
    status: str
    source: str
    compile_session_id: str | None = None
    change_note: str | None = None
    created_at: str
    rule_count: int = 0


class DqaCompileSessionOut(CamelModel):
    id: str
    project_id: str
    study_id: str | None = None
    status: str
    english: str
    provider: str
    model: str
    attempts: int
    latency_ms_total: int
    prompt_tokens: int
    completion_tokens: int
    rule_id: str | None = None
    created_at: str


class DqaEvaluationMetrics(CamelModel):
    duration_ms: float = 0.0
    submissions: int = 0
    rules_evaluated: int = 0
    flags_produced: int = 0
    flagged_submissions: int = 0
    relationship_lookups: int = 0
    relationship_lookup_ms: float = 0.0
    evaluation_errors: list[str] = []
    slow_rules: list[dict[str, Any]] = []
    cascade_projects: list[str] = []
    pack_version: int | None = None


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
    cascade_projects: list[str] | None = None
    metrics: DqaEvaluationMetrics | None = None


class DqaRelationshipOut(CamelModel):
    id: str
    study_id: str
    code: str
    title: str
    source_project_id: str
    target_project_id: str
    source_join_field: str
    target_join_field: str
    cardinality: str


class DqaRelationshipCreate(CamelModel):
    code: str
    title: str = ""
    source_project_id: str
    target_project_id: str
    source_join_field: str
    target_join_field: str
    cardinality: str = "one"


class DqaRelationshipUpdate(CamelModel):
    code: str | None = None
    title: str | None = None
    source_project_id: str | None = None
    target_project_id: str | None = None
    source_join_field: str | None = None
    target_join_field: str | None = None
    cardinality: str | None = None


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


class DqaConversationTurn(CamelModel):
    role: str
    content: str


class DqaCompileInput(CamelModel):
    english: str
    conversation: list[DqaConversationTurn] = []
    existing_rule: dict[str, Any] | None = None
    preview_limit: int = 50


class DqaValidateRuleInput(CamelModel):
    rule: dict[str, Any]
    preview_limit: int = 50


class DqaValidationIssue(CamelModel):
    path: str
    code: str
    message: str


class DqaValidationResult(CamelModel):
    valid: bool
    errors: list[DqaValidationIssue] = []
    warnings: list[str] = []


class DqaTestRuleInput(CamelModel):
    rule: dict[str, Any]
    submission_ids: list[str] = []
    limit: int = 50


class DqaRuleWarning(CamelModel):
    code: str
    message: str


class DqaExplanation(CamelModel):
    summary: str
    lines: list[str] = []
    would_flag: bool = False
    op: str | None = None


class DqaTestRecord(CamelModel):
    submission_id: str
    kobo_id: str | None = None
    enumerator: str | None = None
    outcome: str
    would_flag: bool | None = None
    field_values: dict[str, Any] = {}
    related: list[dict[str, Any]] = []
    explanation: DqaExplanation | dict[str, Any] = {}
    debug_trace: dict[str, Any] = {}
    details: dict[str, Any] = {}


class DqaTestRuleOut(CamelModel):
    submissions_checked: int
    flag_count: int
    pass_count: int
    not_applicable_count: int
    missing_data_count: int = 0
    ambiguous_related_count: int = 0
    records: list[DqaTestRecord] = []
    examples: list[DqaTestRecord] = []
    warnings: list[DqaRuleWarning] = []


class DqaRuleLifecycleInput(CamelModel):
    status: str
    enabled: bool | None = None


class DqaExplainFlagInput(CamelModel):
    rule: dict[str, Any]
    details: dict[str, Any] | None = None
    passes: bool | None = None


class DqaExplainFlagOut(CamelModel):
    explanation: DqaExplanation | dict[str, Any]
    debug_trace: dict[str, Any] = {}


class DqaPreviewExample(CamelModel):
    submission_id: str
    kobo_id: str | None = None
    enumerator: str | None = None
    would_flag: bool | None = None
    details: dict[str, Any] = {}
    outcome: str | None = None
    explanation: dict[str, Any] | None = None


class DqaPreviewResult(CamelModel):
    submissions_checked: int
    flag_count: int
    pass_count: int
    not_applicable_count: int
    examples: list[DqaPreviewExample] = []
    warnings: list[DqaRuleWarning] = []


class DqaResolvedField(CamelModel):
    code: str
    form: str = ""
    label: str = ""


class DqaCompileMeta(CamelModel):
    model: str
    attempts: int
    prompt_id: str | None = None
    session_id: str | None = None
    provider: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class DqaCompileSuccess(CamelModel):
    status: str = "success"
    rule: dict[str, Any]
    explanation: str
    validation: DqaValidationResult
    preview: DqaPreviewResult
    resolved_fields: list[DqaResolvedField] = []
    meta: DqaCompileMeta
    warnings: list[DqaRuleWarning] = []
    diff: dict[str, Any] | None = None
    session_id: str | None = None


class DqaCompileNeedsClarification(CamelModel):
    status: str = "needs_clarification"
    question: str
    partial_explanation: str | None = None
    meta: DqaCompileMeta


class DqaCompileInvalid(CamelModel):
    status: str = "invalid"
    message: str
    validation: DqaValidationResult | None = None
    last_proposal: dict[str, Any] | None = None
    meta: DqaCompileMeta


class DqaValidateRuleOut(CamelModel):
    status: str
    message: str | None = None
    validation: DqaValidationResult
    preview: DqaPreviewResult | None = None
    test: DqaTestRuleOut | None = None
    warnings: list[DqaRuleWarning] = []