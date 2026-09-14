"""Tests for compiling planner JSON into engine ReportSpec / Query IR."""

from __future__ import annotations

from app.domain.reporting.compile import compile_report_spec
from app.domain.reporting.validation import validate_report_spec


def test_compile_measure_operator_sort_and_string_display() -> None:
    raw = {
        "specVersion": "1.0",
        "title": "Compiled",
        "sections": [
            {
                "id": "s1",
                "title": "Intake",
                "components": [
                    {
                        "id": "s1c1",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [
                                {"measure": "count"},
                                {
                                    "measure": "flagged",
                                    "fn": "countWhere",
                                    "field": "isClean",
                                    "eq": False,
                                    "filters": [{"operator": "eq", "field": "x", "value": 1}],
                                },
                            ],
                            "filters": [
                                {"field": "isClean", "operator": "eq", "value": False}
                            ],
                            "sort": {"field": "total", "order": "desc"},
                        },
                        "display": {
                            "items": [
                                {"label": "Total", "field": "count"},
                                {"label": "Flagged", "field": "flagged"},
                            ]
                        },
                    },
                    {
                        "id": "s1c2",
                        "type": "text",
                        "display": "Read-only checklist of open items.",
                    },
                ],
            }
        ],
    }

    compiled = compile_report_spec(raw)
    query = compiled["sections"][0]["components"][0]["query"]
    assert query["measures"][0] == {"id": "count", "fn": "count"}
    assert query["measures"][1] == {
        "id": "flagged",
        "fn": "countWhere",
        "field": "isClean",
        "eq": False,
    }
    assert "filters" not in query["measures"][1]
    assert query["filters"][0]["op"] == "eq"
    assert "operator" not in query["filters"][0]
    assert query["sort"] == {"field": "total", "dir": "desc"}
    assert compiled["sections"][0]["components"][1]["display"] == {
        "body": "Read-only checklist of open items."
    }
    assert "query" not in compiled["sections"][0]["components"][1]

    del compiled["sections"][0]["components"][0]["query"]["sort"]
    errors = validate_report_spec(compiled)
    assert errors == []


def test_compile_is_idempotent_on_golden_shape() -> None:
    golden = {
        "specVersion": "1.0",
        "title": "Golden",
        "sections": [
            {
                "id": "s1",
                "title": "Today",
                "components": [
                    {
                        "id": "s1c1",
                        "type": "table",
                        "query": {
                            "entity": "flag",
                            "window": "execution_date",
                            "filters": [{"field": "severity", "op": "eq", "value": "red"}],
                            "measures": [{"id": "n", "fn": "count"}],
                        },
                        "display": {"columns": ["ruleTitle", "n"]},
                    }
                ],
            }
        ],
    }
    once = compile_report_spec(golden)
    twice = compile_report_spec(once)
    assert once == twice
    assert validate_report_spec(twice) == []


def test_compile_analytics_query_to_query_ir() -> None:
    """Planner catalog used to list 'dimensions'; LLMs copied that onto Query."""
    raw = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {
                "id": "s0",
                "title": "Today",
                "components": [
                    {
                        "id": "s0c1",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {"items": [{"label": "Total", "field": "total"}]},
                    },
                    {
                        "id": "s0c2",
                        "type": "narrative",
                        "uses": ["s0c1"],
                        "query": {},
                        "display": {
                            "role": "insight",
                            "instruction": "Cover new submissions and RED count.",
                        },
                    },
                    {
                        "id": "s0c3",
                        "type": "table",
                        "query": {
                            "dimensions": ["toolCode"],
                            "measures": [
                                {"id": "today", "fn": "count"},
                            ],
                        },
                        "display": {"columns": ["toolCode", "today"]},
                    },
                    {
                        "id": "s0c4",
                        "type": "chart",
                        "query": {
                            "dimensions": ["toolCode"],
                            "measures": [
                                {
                                    "id": "red",
                                    "fn": "countWhere",
                                    "field": "severity",
                                    "eq": "red",
                                },
                                {
                                    "id": "amber",
                                    "fn": "countWhere",
                                    "field": "severity",
                                    "eq": "amber",
                                },
                            ],
                        },
                        "display": {
                            "kind": "stacked_bar",
                            "x": "toolCode",
                            "y": ["red", "amber"],
                        },
                    },
                    {
                        "id": "s0c5",
                        "type": "chart",
                        "query": {
                            "dimensions": ["ruleTitle"],
                            "measures": [{"id": "n", "fn": "count"}],
                        },
                        "display": {
                            "kind": "bar_horizontal",
                            "x": "ruleTitle",
                            "y": ["n"],
                        },
                    },
                ],
            },
            {
                "id": "s1",
                "title": "RED items",
                "components": [
                    {
                        "id": "s1c0",
                        "type": "table",
                        "query": {
                            "dimensions": ["toolCode", "ruleTitle"],
                            "measures": [{"id": "n", "fn": "count"}],
                            "filters": [
                                {"field": "severity", "op": "eq", "value": "red"}
                            ],
                        },
                        "display": {"columns": ["toolCode", "ruleTitle", "n"]},
                    },
                    {
                        "id": "s1c1",
                        "type": "narrative",
                        "uses": ["s1c0"],
                        "query": {"instruction": "Worked example for KoboToolbox."},
                        "display": {
                            "role": "action",
                            "instruction": "Give a worked example so the team can find records.",
                        },
                    },
                ],
            },
        ],
    }

    compiled = compile_report_spec(raw)
    s0 = compiled["sections"][0]["components"]
    assert "query" not in s0[1]
    assert s0[1]["uses"] == ["s0c1"]

    table = s0[2]["query"]
    assert table["entity"] == "submission"
    assert table["window"] == "execution_date"
    assert table["groupBy"] == ["toolCode"]
    assert "dimensions" not in table

    stacked = s0[3]["query"]
    assert stacked["entity"] == "flag"
    assert stacked["groupBy"] == ["toolCode"]
    assert "dimensions" not in stacked

    rules = s0[4]["query"]
    assert rules["entity"] == "flag"
    assert rules["groupBy"] == ["ruleTitle"]

    s1 = compiled["sections"][1]["components"]
    red_table = s1[0]["query"]
    assert red_table["entity"] == "flag"
    assert red_table["groupBy"] == ["toolCode", "ruleTitle"]
    assert "query" not in s1[1]

    assert validate_report_spec(compiled) == []


def test_compile_kpi_group_per_item_queries() -> None:
    raw = {
        "specVersion": "1.0",
        "title": "Glance",
        "sections": [
            {
                "id": "s1",
                "title": "Today",
                "components": [
                    {
                        "id": "glance",
                        "type": "kpi_group",
                        "query": {
                            "entity": "submission",
                            "window": "execution_date",
                            "measures": [{"id": "total", "fn": "count"}],
                        },
                        "display": {
                            "items": [
                                {
                                    "label": "Today",
                                    "query": {
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                                {
                                    "label": "Cumulative",
                                    "query": {
                                        "window": "study_to_date",
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                            ]
                        },
                    }
                ],
            }
        ],
    }
    compiled = compile_report_spec(raw)
    glance = compiled["sections"][0]["components"][0]
    assert "query" not in glance
    items = glance["display"]["items"]
    assert items[0]["query"]["entity"] == "submission"
    assert items[0]["query"]["window"] == "execution_date"
    assert items[1]["query"]["window"] == "study_to_date"
    assert validate_report_spec(compiled) == []
