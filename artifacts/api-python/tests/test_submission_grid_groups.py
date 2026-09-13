"""Unit tests for submission grid survey column grouping."""

from __future__ import annotations

from app.services.submission_grid import _survey_columns


def test_survey_columns_use_labeled_section_not_unlabeled_wrapper() -> None:
    form = {
        "survey": [
            {"type": "begin_group", "name": "group1", "label": None},
            {
                "type": "begin_group",
                "name": "section_a",
                "label": "Section A — From the register",
            },
            {"type": "integer", "name": "A10", "label": "Present today"},
            {"type": "end_group", "name": "section_a"},
            {
                "type": "begin_group",
                "name": "section_b",
                "label": "Section B - Observation",
            },
            {"type": "time", "name": "B2", "label": "Session start"},
            {"type": "end_group", "name": "section_b"},
            {"type": "end_group", "name": "group1"},
        ],
    }
    columns = _survey_columns(form, None)
    by_code = {column["code"]: column for column in columns}
    assert by_code["A10"]["group"] == "section_a"
    assert by_code["A10"]["group_label"] == "Section A — From the register"
    assert by_code["B2"]["group"] == "section_b"
    assert by_code["B2"]["group_label"] == "Section B - Observation"
