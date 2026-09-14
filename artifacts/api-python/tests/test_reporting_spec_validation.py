"""Phase 3 — ReportSpec validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.reporting.spec import ReportSpec
from app.domain.reporting.validation import SpecValidationError, validate_report_spec
from app.services.reporting.config import ReportingConfig

_GOLDEN = Path(__file__).parent / "fixtures" / "reporting_golden_spec.json"


def _golden_dict() -> dict:
    return json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_golden_spec_validates() -> None:
    errors = validate_report_spec(_golden_dict())
    assert errors == []
    ReportSpec.model_validate(_golden_dict())


def test_extra_fields_forbidden() -> None:
    spec = _golden_dict()
    spec["unknownField"] = True
    errors = validate_report_spec(spec)
    assert any("extra" in e.lower() or "unknownField" in e or "forbidden" in e.lower() for e in errors)


def test_bad_entity_rejected() -> None:
    spec = _golden_dict()
    spec["sections"][0]["components"][0]["query"]["entity"] = "widget"
    errors = validate_report_spec(spec)
    assert errors
    assert any("entity" in e.lower() or "widget" in e for e in errors)


def test_iso_date_in_query_window_rejected() -> None:
    spec = _golden_dict()
    spec["sections"][0]["components"][0]["query"]["window"] = "2026-09-12"
    errors = validate_report_spec(spec)
    assert errors
    assert any("window" in e.lower() or "ISO" in e or "2026" in e for e in errors)


def test_text_placeholder_rejected() -> None:
    spec = _golden_dict()
    spec["sections"].append(
        {
            "id": "s4",
            "title": "Note",
            "components": [
                {
                    "id": "s4c1",
                    "type": "text",
                    "display": {"body": "Hello {{name}}"},
                }
            ],
        }
    )
    errors = validate_report_spec(spec)
    assert any("placeholder" in e.lower() or "{{" in e for e in errors)


def test_uses_unknown_id() -> None:
    spec = _golden_dict()
    spec["sections"][2]["components"][1]["uses"] = ["s1c1", "missing-id"]
    errors = validate_report_spec(spec)
    assert any("missing-id" in e for e in errors)


def test_data_source_forbidden() -> None:
    spec = _golden_dict()
    spec["sections"][0]["components"][0]["dataSource"] = "enumerator_performance_today"
    errors = validate_report_spec(spec)
    assert errors
    assert any("dataSource" in e or "Forbidden" in e or "extra" in e.lower() for e in errors)


def test_section_count_knob() -> None:
    cfg = ReportingConfig(spec_sections_max=1)
    errors = validate_report_spec(_golden_dict(), cfg)
    assert any("sections" in e for e in errors)


def test_raise_on_error() -> None:
    with pytest.raises(SpecValidationError):
        validate_report_spec({"specVersion": "1.0", "title": "x", "bogus": 1}, raise_on_error=True)


def test_kpi_group_per_item_queries_validate() -> None:
    spec = {
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
                        "display": {
                            "items": [
                                {
                                    "label": "Submissions today",
                                    "query": {
                                        "entity": "submission",
                                        "window": "execution_date",
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                                {
                                    "label": "Cumulative",
                                    "query": {
                                        "entity": "submission",
                                        "window": "study_to_date",
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                },
                                {
                                    "label": "RED open",
                                    "query": {
                                        "entity": "flag",
                                        "window": "study_to_date",
                                        "measures": [
                                            {
                                                "id": "value",
                                                "fn": "countWhere",
                                                "field": "severity",
                                                "eq": "red",
                                            }
                                        ],
                                    },
                                },
                            ]
                        },
                    }
                ],
            }
        ],
    }
    assert validate_report_spec(spec) == []
    ReportSpec.model_validate(spec)


def test_kpi_group_per_item_rejects_groupby() -> None:
    spec = {
        "specVersion": "1.0",
        "title": "Bad glance",
        "sections": [
            {
                "id": "s1",
                "title": "Today",
                "components": [
                    {
                        "id": "glance",
                        "type": "kpi_group",
                        "display": {
                            "items": [
                                {
                                    "label": "By tool",
                                    "query": {
                                        "entity": "submission",
                                        "window": "execution_date",
                                        "groupBy": ["toolCode"],
                                        "measures": [{"id": "value", "fn": "count"}],
                                    },
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }
    errors = validate_report_spec(spec)
    assert any("groupBy" in e for e in errors)
