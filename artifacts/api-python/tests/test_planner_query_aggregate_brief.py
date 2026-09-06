"""Planner catalog brief includes query_aggregate allowlists from the shared catalog."""

from __future__ import annotations

from app.domain.reporting.query_aggregate_catalog import (
    ENTITY_DIMENSIONS,
    ENTITY_IDS,
    MAX_DISTINCT_DATE_RANGES,
)
from app.services.report_planner.prompting import data_source_brief
from app.services.report_tools import all_descriptors


def test_query_aggregate_brief_embeds_entity_allowlists() -> None:
    brief = {entry["id"]: entry for entry in data_source_brief(all_descriptors())}
    entry = brief["query_aggregate"]
    assert set(entry["entities"]) == set(ENTITY_IDS)
    for entity in ENTITY_IDS:
        assert entry["entities"][entity]["groupBy"] == sorted(ENTITY_DIMENSIONS[entity])
        assert entry["entities"][entity]["filterField"] == sorted(ENTITY_DIMENSIONS[entity])
    assert entry["limits"]["maxDistinctDateRangesPerReport"] == MAX_DISTINCT_DATE_RANGES
    assert "not supported in v1" in entry["limits"]["rateMeasures"]
