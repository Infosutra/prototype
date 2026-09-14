"""Tests for numbered section labels in authoring."""

from __future__ import annotations

from app.services.reporting.section_labels import (
    apply_section_numbers,
    extract_section_asks,
    missing_section_asks,
)


def test_extract_section_asks_keeps_latest_per_number() -> None:
    text = """
Title: DQA Daily Report.
Section 1.1 — Today's intake and flags by tool. Show a table.
Section 1.2 — RED items to correct.
Revise the spec: Section 1.2 — RED items revised title.
Section 1.4 — Coverage and trend. Explain coverage against plan.
"""
    asks = extract_section_asks(text)
    assert [a["number"] for a in asks] == ["1.1", "1.2", "1.4"]
    assert asks[1]["title"] == "RED items revised title"
    assert asks[2]["label"] == "1.4 — Coverage and trend"


def test_extract_honours_remove_and_readd() -> None:
    text = """
Section 1.4 — Coverage and trend. Explain coverage.
remove section 1.4 from the spec
Revise the spec: remove section 1.4 from the spec
Omit section 1.4 from the report.
"""
    assert extract_section_asks(text) == []
    text2 = text + "\nSection 1.4 — Coverage and trend. Explain again."
    asks = extract_section_asks(text2)
    assert [a["number"] for a in asks] == ["1.4"]


def test_apply_section_numbers_rewrites_titles() -> None:
    spec = {
        "title": "DQA Daily Report",
        "sections": [
            {"id": "kpi", "title": "Today's Intake and Flags"},
            {"id": "by_tool", "title": "Today's Intake and Flags by Tool"},
            {"id": "red", "title": "RED Items to Correct or Back-Check"},
        ],
    }
    asks = extract_section_asks(
        "Section 1.1 — Today's intake and flags by tool.\n"
        "Section 1.2 — RED items to correct or back-check."
    )
    out = apply_section_numbers(spec, asks)
    assert out is not None
    titles = [s["title"] for s in out["sections"]]
    assert titles[0] == "Today's Intake and Flags"
    assert titles[1] == "1.1 — Today's Intake and Flags by Tool"
    assert titles[2] == "1.2 — RED Items to Correct or Back-Check"


def test_missing_section_asks_detects_dropped_coverage() -> None:
    spec = {
        "sections": [
            {"id": "a", "title": "1.1 — Today's Intake and Flags by Tool"},
            {"id": "b", "title": "1.2 — RED Items"},
            {"id": "c", "title": "1.3 — Enumerators to Back-Check Tomorrow"},
        ]
    }
    asks = extract_section_asks(
        "Section 1.1 — Today's intake and flags by tool.\n"
        "Section 1.2 — RED items.\n"
        "Section 1.3 — Enumerators to back-check tomorrow.\n"
        "Section 1.4 — Coverage and trend."
    )
    missing = missing_section_asks(spec, asks)
    assert len(missing) == 1
    assert missing[0]["number"] == "1.4"


def test_signoff_checklist_detection_and_scaffold() -> None:
    from app.services.reporting.section_labels import (
        merge_scaffolded_section,
        next_section_number,
        scaffold_signoff_section,
        spec_has_signoff_section,
        wants_signoff_checklist,
    )

    assert wants_signoff_checklist(
        "Close with the read-only sign-off checklist of open RED and AMBER items."
    )
    assert not wants_signoff_checklist("Section 1.1 — Today's intake by tool.")

    spec = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {"id": "kpi", "title": "Today's Intake and Flags", "components": []},
            {
                "id": "section_1_5",
                "title": "1.5 — Submission Quality by Enumerator",
                "components": [],
            },
        ],
    }
    assert next_section_number(spec) == "1.6"
    assert not spec_has_signoff_section(spec)
    section = scaffold_signoff_section(spec=spec)
    assert section["title"].startswith("1.6")
    ids = [c["id"] for c in section["components"]]
    assert ids == ["signoff_note", "open_red_items", "open_amber_items"]
    merged = merge_scaffolded_section(spec, section)
    assert merged is not None
    assert spec_has_signoff_section(merged)


def test_missing_ask_issues_explains_enumerator_quality() -> None:
    from app.services.reporting.plan_explain import partial_issue_question
    from app.services.reporting.section_labels import missing_ask_issues

    instructions = (
        "Section 1.5 — Submission quality by enumerator: forms submitted, clean forms, "
        "flagged forms and the exact DQA issues raised"
    )
    asks = extract_section_asks(instructions)
    issues = missing_ask_issues(asks, instructions=instructions)
    assert len(issues) == 1
    reason = issues[0]["reason"].lower()
    assert "1.5" in reason
    assert "enumerator" in reason
    assert "clean" in reason or "isclean" in reason
    assert "dqa" in reason
    assert issues[0].get("droppedComponent", {}).get("type") == "table"
    question = partial_issue_question(
        issues[0]["reason"], dropped_component=issues[0]["droppedComponent"]
    )
    labels = [str(o.get("label") or "") for o in question.get("options") or []]
    assert any("table" in label.lower() for label in labels)
    assert any("bar" in label.lower() for label in labels)


def test_scaffold_enumerator_quality_merges() -> None:
    from app.services.reporting.section_labels import (
        merge_scaffolded_section,
        scaffold_section_for_ask,
    )

    instructions = (
        "Section 1.5 — Submission quality by enumerator: forms submitted, clean forms, "
        "flagged forms and the exact DQA issues raised"
    )
    ask = extract_section_asks(instructions)[0]
    section = scaffold_section_for_ask(ask, visual="table", instructions=instructions)
    ids = [c["id"] for c in section["components"]]
    assert "quality_by_enumerator" in ids
    assert "dqa_issues_by_enumerator" in ids
    merged = merge_scaffolded_section(
        {"specVersion": "1.0", "title": "DQA Daily Report", "sections": []},
        section,
    )
    assert merged is not None
    assert missing_section_asks(merged, [ask]) == []


def test_missing_ask_issues_explains_flag_rate_limits() -> None:
    from app.services.reporting.section_labels import missing_ask_issues

    instructions = (
        "Section 1.4 — Coverage and trend. Explain coverage against plan and how the "
        "cumulative flag rate has moved, then show cumulative submissions against target "
        "by tool and the flag rate by study day."
    )
    asks = extract_section_asks(instructions)
    issues = missing_ask_issues(asks, instructions=instructions)
    assert len(issues) == 1
    reason = issues[0]["reason"].lower()
    assert "1.4" in reason
    assert "flag rate" in reason
    assert "built-in" in reason or "does not have" in reason
    assert "rephrase it around what to group by" not in reason
    assert issues[0].get("droppedComponent", {}).get("type") == "chart"


def test_scaffold_bar_section_merges_when_missing() -> None:
    from app.services.reporting.section_labels import (
        merge_scaffolded_section,
        scaffold_section_for_ask,
    )

    spec = {
        "specVersion": "1.0",
        "title": "DQA Daily Report",
        "sections": [
            {
                "id": "kpi",
                "title": "Today's Intake and Flags",
                "components": [
                    {
                        "id": "glance",
                        "type": "kpi_group",
                        "display": {
                            "items": [
                                {
                                    "label": "Today",
                                    "query": {
                                        "entity": "submission",
                                        "window": "execution_date",
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
    ask = {
        "number": "1.4",
        "title": "Coverage and trend",
        "label": "1.4 — Coverage and trend",
    }
    instructions = (
        "Section 1.4 — Coverage and trend. Explain coverage against plan and the "
        "flag rate by study day, then cumulative submissions against target by tool."
    )
    section = scaffold_section_for_ask(ask, visual="bar", instructions=instructions)
    merged = merge_scaffolded_section(spec, section)
    assert merged is not None
    titles = [s["title"] for s in merged["sections"]]
    assert "1.4 — Coverage and trend" in titles
    assert missing_section_asks(merged, [ask]) == []


def test_scaffold_section_from_free_text_signoff() -> None:
    from app.services.reporting.section_labels import (
        scaffold_section_from_free_text,
        spec_has_signoff_section,
    )

    section = scaffold_section_from_free_text(
        "Close with a read-only sign-off checklist of open RED and AMBER items.",
        spec={"sections": [{"id": "s1", "title": "1.1 — Intake", "components": []}]},
    )
    assert section is not None
    assert "Sign-off" in section["title"] or "sign" in section["title"].lower()
    merged = {
        "specVersion": "1.0",
        "title": "T",
        "sections": [
            {"id": "s1", "title": "1.1 — Intake", "components": []},
            section,
        ],
    }
    assert spec_has_signoff_section(merged)


def test_append_components_to_section_renames_ids() -> None:
    from app.services.reporting.section_labels import (
        append_components_to_section,
        scaffold_signoff_section,
    )

    spec = {
        "specVersion": "1.0",
        "title": "T",
        "sections": [
            {
                "id": "s1",
                "title": "1.1 — Intake",
                "components": [
                    {
                        "id": "open_red_items",
                        "type": "table",
                        "query": {
                            "entity": "flag",
                            "window": "study_to_date",
                            "filters": [{"field": "severity", "op": "eq", "value": "red"}],
                            "limit": 50,
                        },
                        "display": {
                            "columns": ["toolCode", "ruleTitle", "enumerator", "severity"]
                        },
                    }
                ],
            }
        ],
    }
    extra = scaffold_signoff_section(number="9", spec=spec)["components"]
    # Only the colliding red table id — keep the test focused on rename.
    extra = [c for c in extra if c["id"] == "open_red_items"]
    merged = append_components_to_section(spec, section_id="s1", components=extra)
    assert merged is not None
    ids = [c["id"] for c in merged["sections"][0]["components"]]
    assert ids == ["open_red_items", "open_red_items_2"]


def test_section_asks_for_missing_check_scopes_to_latest_turn() -> None:
    from app.services.reporting.section_labels import section_asks_for_missing_check

    instructions = (
        "Section 1.1 — Today's intake.\n"
        "Section 1.4 — Coverage and trend. Flag rate by study day.\n"
        "Omit section 1.4 from the report.\n"
        "Section 1.4 — Coverage and trend. Flag rate by study day."
    )
    # Later unrelated turn should not re-nag about historical 1.4.
    assert (
        section_asks_for_missing_check(
            instructions=instructions,
            latest_message="Rename the report title to Weekly DQA.",
        )
        == []
    )
    # Clarifying the open 1.4 failure still scopes to 1.4.
    scoped = section_asks_for_missing_check(
        instructions=instructions,
        latest_message="Try as a bar chart",
        clarifying_question={
            "kind": "plan_partial",
            "prompt": 'I couldn\'t add “1.4 — Coverage and trend” yet.',
        },
    )
    assert [a["number"] for a in scoped] == ["1.4"]
    # A newly typed Section ask is checked.
    scoped2 = section_asks_for_missing_check(
        instructions=instructions,
        latest_message="Section 1.5 — Field notes. Show a short table of open AMBER rules.",
    )
    assert [a["number"] for a in scoped2] == ["1.5"]
