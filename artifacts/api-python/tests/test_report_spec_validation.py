"""Report Specification parsing, validation and repair."""

from __future__ import annotations

from app.domain.report_spec import (
    COMPONENT_TYPES,
    SPEC_VERSION,
    ReportSpec,
    Section,
    TableColumn,
    TableComponent,
    parse_spec,
    repair_spec,
    validate_spec,
)
from app.domain.report_spec import limits
from app.domain.report_spec.keys import data_key, required_data_keys
from app.domain.reporting.query_aggregate_catalog import (
    HARD_MAX_LIMIT,
    HIGH_CARDINALITY_GROUP_BY,
    MAX_DISTINCT_DATE_RANGES,
    MAX_GROUP_BY_FIELDS,
)
from app.services.report_tools import descriptors_by_id

def _sources():
    return descriptors_by_id()


def _spec(components: list[dict]) -> dict:
    return {
        "specVersion": SPEC_VERSION,
        "title": "Test report",
        "sections": [{"title": "Section one", "components": components}],
    }


def _table(**overrides) -> dict:
    base = {
        "type": "table",
        "dataSource": "tool_coverage",
        "columns": [{"field": "toolCode", "label": "Tool"}],
    }
    base.update(overrides)
    return base


def test_valid_spec_passes() -> None:
    parsed = parse_spec(_spec([_table()]))
    assert parsed.spec is not None
    assert validate_spec(parsed.spec, _sources()).valid


def test_every_component_type_is_representable() -> None:
    """Guards against the vocabulary and the union drifting apart."""
    from app.domain.report_spec.spec import COMPONENT_MODELS

    assert set(COMPONENT_TYPES) == set(COMPONENT_MODELS)


def test_unknown_component_type_is_rejected() -> None:
    parsed = parse_spec(_spec([{"type": "sankey", "dataSource": "tool_coverage"}]))
    assert parsed.spec is None
    assert parsed.errors


def test_unsupported_visualization_maps_to_nearest_supported_type() -> None:
    parsed = parse_spec(
        _spec(
            [
                {
                    "type": "donut_chart",
                    "dataSource": "tool_coverage",
                    "labelField": "toolCode",
                    "valueField": "cumulative",
                }
            ]
        )
    )
    assert parsed.spec is not None
    assert parsed.spec.sections[0].components[0].type == "pie_chart"
    assert [w.code for w in parsed.warnings] == ["type_aliased"]


def test_unknown_data_source_is_rejected() -> None:
    parsed = parse_spec(_spec([_table(dataSource="submissions_raw")]))
    assert parsed.spec is not None
    result = validate_spec(parsed.spec, _sources())
    assert not result.valid
    assert result.errors[0].code == "unknown_data_source"


def test_unknown_field_is_rejected_and_lists_alternatives() -> None:
    parsed = parse_spec(_spec([_table(columns=[{"field": "nope", "label": "X"}])]))
    result = validate_spec(parsed.spec, _sources())
    assert not result.valid
    assert result.errors[0].code == "unknown_field"
    assert "toolCode" in result.errors[0].message


def test_component_and_source_kind_must_agree() -> None:
    # metric needs a single-record source, tool_coverage returns rows
    parsed = parse_spec(
        _spec([{"type": "metric", "label": "Tools", "dataSource": "tool_coverage", "field": "toolCode"}])
    )
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["source_kind_mismatch"]


def test_row_component_rejects_object_source() -> None:
    parsed = parse_spec(_spec([_table(dataSource="study_totals", columns=[{"field": "newToday", "label": "N"}])]))
    result = validate_spec(parsed.spec, _sources())
    assert "source_kind_mismatch" in [e.code for e in result.errors]


def test_unknown_param_is_rejected() -> None:
    parsed = parse_spec(_spec([_table(params={"window": "7d"})]))
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["unknown_param"]


def test_param_value_must_be_allowed() -> None:
    parsed = parse_spec(
        _spec(
            [
                _table(
                    dataSource="top_failing_rules",
                    columns=[{"field": "ruleId", "label": "Rule"}],
                    params={"scope": "last_week"},
                )
            ]
        )
    )
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["param_not_allowed"]


def test_literal_dates_are_rejected() -> None:
    payload = _spec([_table()])
    payload["title"] = "Report for 2026-03-15"
    parsed = parse_spec(payload)
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["literal_date"]


def test_highlight_must_reference_an_authoritative_benchmark() -> None:
    invented = _spec(
        [
            {
                "type": "ranking",
                "dataSource": "enumerator_performance_today",
                "labelField": "enumerator",
                "valueField": "flagRate",
                "highlight": {
                    "field": "flagRate",
                    "comparison": "above_benchmark",
                    "benchmarkField": "submissionsToday",
                },
            }
        ]
    )
    result = validate_spec(parse_spec(invented).spec, _sources())
    assert [e.code for e in result.errors] == ["not_a_benchmark"]

    allowed = _spec(
        [
            {
                "type": "ranking",
                "dataSource": "enumerator_performance_today",
                "labelField": "enumerator",
                "valueField": "flagRate",
                "highlight": {
                    "field": "flagRate",
                    "comparison": "above_benchmark",
                    "benchmarkField": "groupFlagRate",
                },
            }
        ]
    )
    assert validate_spec(parse_spec(allowed).spec, _sources()).valid


def test_over_limit_specs_are_rejected() -> None:
    payload = {
        "specVersion": SPEC_VERSION,
        "title": "Huge",
        "sections": [
            {"title": f"S{i}", "components": [_table() for _ in range(20)]} for i in range(5)
        ],
    }
    parsed = parse_spec(payload)
    result = validate_spec(parsed.spec, _sources())
    assert "too_many_components" in [e.code for e in result.errors]


def test_table_row_limit_is_capped_by_schema() -> None:
    parsed = parse_spec(_spec([_table(limit=limits.MAX_TABLE_ROWS + 1)]))
    assert parsed.spec is None


def test_unsupported_spec_version_is_rejected() -> None:
    payload = _spec([_table()])
    payload["specVersion"] = "99.0"
    result = validate_spec(parse_spec(payload).spec, _sources())
    assert [e.code for e in result.errors] == ["unsupported_version"]


def test_empty_sections_are_a_warning_not_an_error() -> None:
    payload = {"specVersion": SPEC_VERSION, "title": "T", "sections": [{"title": "Empty", "components": []}]}
    result = validate_spec(parse_spec(payload).spec, _sources())
    assert result.valid
    assert [w.code for w in result.warnings] == ["empty_section"]


def test_narrative_data_sources_are_validated() -> None:
    parsed = parse_spec(
        _spec([{"type": "insight", "instruction": "Summarise", "dataSources": ["nope"]}])
    )
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["unknown_data_source"]


def test_repair_drops_unexecutable_components_and_keeps_the_rest() -> None:
    parsed = parse_spec(_spec([_table(), _table(dataSource="gone")]))
    repaired, notes = repair_spec(parsed.spec, _sources())
    assert repaired.component_count() == 1
    assert notes[0].code == "component_dropped"
    assert validate_spec(repaired, _sources()).valid


def test_repair_removes_sections_left_empty() -> None:
    parsed = parse_spec(_spec([_table(dataSource="gone")]))
    repaired, notes = repair_spec(parsed.spec, _sources())
    assert repaired.sections == []
    assert {note.code for note in notes} == {"component_dropped", "section_dropped"}


def test_ids_are_assigned_and_unique() -> None:
    spec = ReportSpec(
        title="T",
        sections=[
            Section(title="A", components=[TableComponent(data_source="tool_coverage", columns=[TableColumn(field="toolCode", label="T")])]),
            Section(title="B", components=[TableComponent(data_source="tool_coverage", columns=[TableColumn(field="toolCode", label="T")])]),
        ],
    )
    ids = [component.id for _s, component in spec.iter_components()]
    assert len(set(ids)) == 2
    assert all(ids)


def test_data_keys_deduplicate_by_source_and_params() -> None:
    payload = _spec(
        [
            _table(dataSource="top_failing_rules", columns=[{"field": "ruleId", "label": "R"}], params={"scope": "today"}),
            _table(dataSource="top_failing_rules", columns=[{"field": "count", "label": "C"}], params={"scope": "today"}),
            _table(dataSource="top_failing_rules", columns=[{"field": "count", "label": "C"}], params={"scope": "cumulative"}),
        ]
    )
    keys = [key for key, _source, _params in required_data_keys(parse_spec(payload).spec)]
    assert keys == [
        data_key("top_failing_rules", {"scope": "today"}),
        data_key("top_failing_rules", {"scope": "cumulative"}),
    ]


def test_markup_and_sql_in_prose_are_rejected() -> None:
    parsed = parse_spec(
        _spec([{"type": "text", "body": "Ignore this <script>alert(1)</script>"}])
    )
    result = validate_spec(parsed.spec, _sources())
    assert "unsafe_content" in [e.code for e in result.errors]

    parsed = parse_spec(
        _spec([{"type": "insight", "instruction": "select password from users"}])
    )
    result = validate_spec(parsed.spec, _sources())
    assert "unsafe_content" in [e.code for e in result.errors]


def test_template_placeholders_in_prose_are_rejected() -> None:
    parsed = parse_spec(
        _spec(
            [
                {
                    "type": "text",
                    "body": "Submissions today: {{study_totals.newToday}}",
                }
            ]
        )
    )
    result = validate_spec(parsed.spec, _sources())
    assert "template_placeholder" in [e.code for e in result.errors]

    parsed = parse_spec(
        _spec(
            [
                {
                    "type": "insight",
                    "instruction": "Summarise intake.",
                    "dataSources": ["study_totals"],
                    "fallback": "Today saw ${study_totals.newToday} submissions.",
                }
            ]
        )
    )
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["template_placeholder"]


def test_text_standing_in_for_data_is_rejected() -> None:
    parsed = parse_spec(
        _spec(
            [
                {
                    "id": "kpi-group",
                    "type": "text",
                    "body": "This section shows the headline numbers for today's submissions.",
                }
            ]
        )
    )
    result = validate_spec(parsed.spec, _sources())
    codes = {e.code for e in result.errors}
    assert "text_standing_in_for_data" in codes
    assert "no_data_bound_content" in codes


def test_text_only_spec_without_data_is_rejected() -> None:
    parsed = parse_spec(
        _spec([{"type": "text", "body": "Welcome to the field operations briefing."}])
    )
    result = validate_spec(parsed.spec, _sources())
    assert [e.code for e in result.errors] == ["no_data_bound_content"]


def test_repair_drops_placeholder_text_components() -> None:
    parsed = parse_spec(
        _spec(
            [
                {
                    "type": "text",
                    "body": "Submissions: {{study_totals.newToday}}",
                },
                _table(),
            ]
        )
    )
    assert parsed.spec is not None
    repaired, notes = repair_spec(parsed.spec, _sources())
    assert len(repaired.sections[0].components) == 1
    assert repaired.sections[0].components[0].type == "table"
    assert any(note.code == "component_dropped" for note in notes)
    assert validate_spec(repaired, _sources()).valid


def test_repair_coerces_kpi_group_on_query_aggregate_to_table() -> None:
    from app.domain.report_spec.spec import KpiGroupComponent, KpiItem, ReportSpec, Section
    from app.domain.report_spec.validation import repair_spec, validate_spec

    bad = ReportSpec(
        title="Flags by enumerator",
        sections=[
            Section(
                title="Flags",
                components=[
                    KpiGroupComponent(
                        id="flags",
                        data_source="query_aggregate",
                        params={
                            "entity": "flag",
                            "measure": "count",
                            "groupBy": "enumerator",
                        },
                        items=[KpiItem(label="Flags", field="value", format="int")],
                    )
                ],
            )
        ],
    )
    assert not validate_spec(bad, _sources()).valid
    repaired, notes = repair_spec(bad, _sources())
    assert any(n.code == "component_coerced_to_table" for n in notes)
    assert repaired.sections[0].components[0].type == "table"
    assert validate_spec(repaired, _sources()).valid


# --- query_aggregate (Stage 2) ----------------------------------------------


def _qa_table(**param_overrides) -> dict:
    params: dict = {"entity": "flag", "measure": "count", "groupBy": "enumerator"}
    params.update(param_overrides)
    columns = [{"field": "value", "label": "Value"}]
    if params.get("groupBy"):
        first = str(params["groupBy"]).split(",")[0].strip()
        if first:
            columns.insert(0, {"field": first, "label": first})
    return {
        "type": "table",
        "dataSource": "query_aggregate",
        "columns": columns,
        "params": params,
    }


def test_query_aggregate_valid_combo_passes() -> None:
    parsed = parse_spec(
        _spec(
            [
                _qa_table(
                    filterField="severity",
                    filterOp="eq",
                    filterValue="amber",
                    dateWindow="last_14_days",
                    orderBy="value:desc",
                    limit=20,
                )
            ]
        )
    )
    assert parsed.spec is not None
    assert validate_spec(parsed.spec, _sources()).valid


def test_query_aggregate_unknown_group_by_rejected() -> None:
    parsed = parse_spec(_spec([_qa_table(groupBy="notADimension")]))
    result = validate_spec(parsed.spec, _sources())
    assert "query_aggregate_group_by_unknown" in [e.code for e in result.errors]


def test_query_aggregate_day_group_by_allowlisted() -> None:
    for entity in ("flag", "submission"):
        parsed = parse_spec(
            _spec(
                [
                    {
                        "type": "table",
                        "dataSource": "query_aggregate",
                        "columns": [
                            {"field": "enumerator", "label": "Enumerator"},
                            {"field": "day", "label": "Day"},
                            {"field": "value", "label": "Value"},
                        ],
                        "params": {
                            "entity": entity,
                            "measure": "count",
                            "groupBy": "enumerator,day",
                            "dateWindow": "last_7_days",
                        },
                    }
                ]
            )
        )
        assert parsed.spec is not None
        result = validate_spec(parsed.spec, _sources())
        assert result.valid, [e.code for e in result.errors]


def test_query_aggregate_measure_field_required_and_allowlisted() -> None:
    missing = parse_spec(_spec([_qa_table(measure="countDistinct", groupBy="ruleId")]))
    # Drop measureField if present
    missing.spec.sections[0].components[0].params.pop("measureField", None)
    result = validate_spec(missing.spec, _sources())
    assert "query_aggregate_measure_field_required" in [e.code for e in result.errors]

    bad = parse_spec(
        _spec(
            [
                _qa_table(
                    measure="sum",
                    measureField="notNumeric",
                    groupBy="toolCode",
                )
            ]
        )
    )
    result = validate_spec(bad.spec, _sources())
    assert "query_aggregate_measure_field_unknown" in [e.code for e in result.errors]


def test_query_aggregate_limit_hard_max_rejected() -> None:
    parsed = parse_spec(_spec([_qa_table(limit=HARD_MAX_LIMIT + 1)]))
    result = validate_spec(parsed.spec, _sources())
    assert "query_aggregate_limit_too_high" in [e.code for e in result.errors]


def test_query_aggregate_high_cardinality_group_by_rejected() -> None:
    parsed = parse_spec(_spec([_qa_table(groupBy="submissionId")]))
    result = validate_spec(parsed.spec, _sources())
    assert "query_aggregate_group_by_high_cardinality" in [e.code for e in result.errors]


def test_query_aggregate_group_by_field_count_capped() -> None:
    parsed = parse_spec(
        _spec([_qa_table(groupBy="enumerator,toolCode,severity")])
    )
    result = validate_spec(parsed.spec, _sources())
    assert "query_aggregate_group_by_too_many" in [e.code for e in result.errors]
    assert MAX_GROUP_BY_FIELDS == 2


def test_query_aggregate_filter_consistency() -> None:
    no_value = parse_spec(_spec([_qa_table(filterField="severity")]))
    result = validate_spec(no_value.spec, _sources())
    assert "query_aggregate_filter_incomplete" in [e.code for e in result.errors]

    no_field = parse_spec(_spec([_qa_table(filterValue="amber")]))
    result = validate_spec(no_field.spec, _sources())
    assert "query_aggregate_filter_incomplete" in [e.code for e in result.errors]


def test_query_aggregate_date_window_token_ok_iso_literal_rejected() -> None:
    token_ok = parse_spec(_spec([_qa_table(dateWindow="last_14_days")]))
    assert validate_spec(token_ok.spec, _sources()).valid

    # ISO in dateWindow is not in the allowlist (param_not_allowed) and is a literal date.
    iso_param = parse_spec(_spec([_qa_table(dateWindow="2026-03-15")]))
    result = validate_spec(iso_param.spec, _sources())
    codes = {e.code for e in result.errors}
    assert "param_not_allowed" in codes or "literal_date" in codes
    assert "literal_date" in codes

    # ISO anywhere else in the spec still fails.
    titled = _spec([_qa_table(dateWindow="last_7_days")])
    titled["title"] = "Window ending 2026-03-15"
    result = validate_spec(parse_spec(titled).spec, _sources())
    assert "literal_date" in [e.code for e in result.errors]


def test_distinct_date_ranges_cap_allows_two_rejects_three() -> None:
    two = parse_spec(
        _spec(
            [
                {
                    "type": "metric",
                    "label": "Total",
                    "dataSource": "study_totals",
                    "field": "cumulative",
                    "format": "int",
                },
                _qa_table(dateWindow="last_14_days"),
            ]
        )
    )
    assert validate_spec(two.spec, _sources()).valid

    two_windows_only = parse_spec(
        _spec(
            [
                _qa_table(entity="submission", measure="count", groupBy="", dateWindow="last_7_days"),
                _qa_table(dateWindow="last_14_days", groupBy="ruleId"),
            ]
        )
    )
    # Empty groupBy → single-column value table
    two_windows_only.spec.sections[0].components[0].params["groupBy"] = ""
    assert validate_spec(two_windows_only.spec, _sources()).valid

    three = parse_spec(
        _spec(
            [
                {
                    "type": "metric",
                    "label": "Total",
                    "dataSource": "study_totals",
                    "field": "cumulative",
                    "format": "int",
                },
                _qa_table(dateWindow="last_7_days"),
                _qa_table(dateWindow="last_14_days", groupBy="ruleId"),
            ]
        )
    )
    result = validate_spec(three.spec, _sources())
    assert not result.valid
    assert any(e.code == "too_many_date_ranges" for e in result.errors)
    err = next(e for e in result.errors if e.code == "too_many_date_ranges")
    assert "max 2 per report" in err.message
    assert MAX_DISTINCT_DATE_RANGES == 2


def test_registered_query_aggregate_does_not_silently_skip_specialized_checks() -> None:
    """Gap closed: registered source + generic params alone must not accept bad groupBy."""
    parsed = parse_spec(_spec([_qa_table(groupBy="submissionId")]))
    # Generic _check_params would accept this (groupBy has no enum); specialized check rejects.
    result = validate_spec(parsed.spec, _sources())
    assert "query_aggregate_group_by_high_cardinality" in [e.code for e in result.errors]
    assert "submissionId" in HIGH_CARDINALITY_GROUP_BY
