"""Eval cases: natural-language prompts map onto registered data sources."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.report_spec.spec import (
    HighlightRule,
    MetricComponent,
    RankingComponent,
    ReportSpec,
    Section,
    TableColumn,
    TableComponent,
)
from app.domain.report_spec.validation import validate_spec
from app.services.report_tools import descriptors_by_id

CASES = Path(__file__).resolve().parent / "fixtures" / "report_eval_cases.json"


def test_eval_cases_resolve_to_valid_specs() -> None:
    sources = descriptors_by_id()
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert cases, "eval case file is empty"
    for case in cases:
        for source_id in case["dataSources"]:
            assert source_id in sources, f"{case['id']} references unknown source {source_id}"
        first = case["dataSources"][0]
        descriptor = sources[first]
        if case.get("requiresBenchmarkHighlight"):
            component = RankingComponent(
                id="rank",
                data_source=first,
                label_field=descriptor.fields[0].name,
                value_field=next(
                    field.name for field in descriptor.fields if field.type == "percent"
                ),
                highlight=HighlightRule(
                    field=next(
                        field.name for field in descriptor.fields if field.type == "percent"
                    ),
                    comparison="above_benchmark",
                    benchmark_field=descriptor.benchmark_fields[0],
                ),
            )
        elif descriptor.kind == "object":
            component = MetricComponent(
                id="m",
                label=descriptor.fields[0].label,
                data_source=first,
                field=descriptor.fields[0].name,
            )
        else:
            field = descriptor.fields[0].name
            component = TableComponent(
                id="t",
                data_source=first,
                columns=[TableColumn(field=field, label=field)],
            )
        spec = ReportSpec(
            title=case["prompt"],
            sections=[Section(title=case["id"], components=[component])],
        )
        result = validate_spec(spec, sources)
        assert result.valid, f"{case['id']}: {[e.message for e in result.errors]}"
