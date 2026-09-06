"""Seeded system report templates.

The DQA Daily template is the reference specification: it reproduces the report the
application shipped before templates existed, expressed entirely as data. It is
also the worked example a planner is shown when composing new reports.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReportTemplate, ReportTemplateVersion
from app.domain.report_spec.spec import (
    BarChartComponent,
    ChartSeries,
    KpiGroupComponent,
    KpiItem,
    LineChartComponent,
    NarrativeComponent,
    ProgressComponent,
    ReportSpec,
    Section,
    SortSpec,
    TableColumn,
    TableComponent,
    TextComponent,
)
from app.services.report_templates import add_version, create_template

logger = logging.getLogger(__name__)

DAILY_TEMPLATE_ID = "seed-dqa-daily-template"
FINAL_TEMPLATE_ID = "seed-dqa-final-template"

DAILY_TEMPLATE_PROMPT = """Create the daily data quality report for the study.

Title: DQA Daily Report.

Open with today's intake as KPI cards: submissions received today, cumulative submissions, and open
RED and AMBER flags. Follow with a short headline paragraph covering new submissions, the RED count
to back-check tomorrow, and the leading AMBER theme.

Section 1.1 — Today's intake and flags by tool. Show a table with one row per tool giving new
submissions today, cumulative submissions, RED today, AMBER today and the percentage of today's
submissions flagged. Add a stacked bar chart of today's RED and AMBER by tool, and a horizontal bar
chart of the rules failing most often today.

Section 1.2 — RED items to correct or back-check, grouped by tool and rule, with record counts and a
worked example so the team can find the records in KoboToolbox.

Section 1.3 — Enumerators to back-check tomorrow: records submitted today, flag rate, median
interview time and why their records were flagged, worst first.

Section 1.4 — Coverage and trend. Explain coverage against plan and how the cumulative flag rate has
moved, then show cumulative submissions against target by tool and the flag rate by study day.

Section 1.5 — Submission quality by enumerator: forms submitted, clean forms, flagged forms and the
exact DQA issues raised.

Close with the read-only sign-off checklist of open RED and AMBER items."""


def build_daily_dqa_spec() -> ReportSpec:
    """The Daily DQA report expressed as a specification."""
    return ReportSpec(
        title="DQA Daily Report",
        subtitle="Same-day data quality review for field back-checks",
        sections=[
            Section(
                id="intake",
                title="Today at a glance",
                components=[
                    KpiGroupComponent(
                        id="intake-kpis",
                        data_source="study_totals",
                        items=[
                            KpiItem(label="Submissions today", field="newToday", format="int"),
                            KpiItem(label="Cumulative", field="cumulative", format="int"),
                            KpiItem(label="RED open", field="redOpen", format="int"),
                            KpiItem(label="AMBER open", field="amberOpen", format="int"),
                            KpiItem(
                                label="% flagged today", field="flaggedPctToday", format="percent"
                            ),
                        ],
                    ),
                    NarrativeComponent(
                        id="headline",
                        type="insight",
                        title="Today's headline",
                        instruction=(
                            "In one to three sentences, state how many submissions arrived today, "
                            "how many RED items need back-checking tomorrow, and the leading AMBER "
                            "theme by tool."
                        ),
                        data_sources=["study_totals", "tool_coverage", "top_failing_rules"],
                        fallback="daily_headline",
                        max_words=120,
                    ),
                ],
            ),
            Section(
                id="s11",
                title="1.1 Today's intake & flags — by tool",
                components=[
                    TableComponent(
                        id="s11-tools",
                        data_source="tool_coverage",
                        columns=[
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(
                                field="newToday", label="New today", align="right", format="int"
                            ),
                            TableColumn(
                                field="cumulative", label="Cumulative", align="right", format="int"
                            ),
                            TableColumn(
                                field="redToday", label="RED today", align="right", format="int"
                            ),
                            TableColumn(
                                field="amberToday", label="AMBER today", align="right", format="int"
                            ),
                            TableColumn(
                                field="flaggedPctToday",
                                label="% flagged (today)",
                                align="right",
                                format="percent",
                            ),
                        ],
                        limit=25,
                    ),
                    TextComponent(
                        id="s11-note",
                        body=(
                            "Today's flag rate is inflated by same-day records not yet "
                            "back-checked; the cumulative trend in section 1.4 is the truer picture."
                        ),
                    ),
                    BarChartComponent(
                        id="s11-flags",
                        title="Today's RED / AMBER by tool",
                        data_source="tool_coverage",
                        x="toolCode",
                        series=[
                            ChartSeries(field="redToday", label="RED", color="red"),
                            ChartSeries(field="amberToday", label="AMBER", color="amber"),
                        ],
                        y_label="Flags today",
                        caption="Figure — Today's RED / AMBER flag counts by tool.",
                    ),
                    BarChartComponent(
                        id="s11-rules",
                        title="Top failing rules today",
                        data_source="top_failing_rules",
                        params={"scope": "today"},
                        x="ruleId",
                        series=[ChartSeries(field="count", label="Records", color="red")],
                        orientation="horizontal",
                        sort=SortSpec(field="count", direction="desc"),
                        limit=8,
                        y_label="Records",
                        caption="Figure — Rules failing most often today.",
                    ),
                ],
            ),
            Section(
                id="s12",
                title="1.2 RED items to correct or back-check (priority)",
                components=[
                    TableComponent(
                        id="s12-red",
                        data_source="red_priority_items",
                        columns=[
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(field="ruleId", label="Rule"),
                            TableColumn(field="title", label="Check"),
                            TableColumn(
                                field="count", label="Records", align="right", format="int"
                            ),
                            TableColumn(field="example", label="Example"),
                        ],
                        sort=SortSpec(field="count", direction="desc"),
                        limit=25,
                        empty_text="No RED items today.",
                    ),
                ],
            ),
            Section(
                id="s13",
                title="1.3 Enumerators to back-check tomorrow",
                components=[
                    TableComponent(
                        id="s13-enumerators",
                        data_source="enumerator_performance_today",
                        columns=[
                            TableColumn(field="enumerator", label="Enumerator"),
                            TableColumn(field="tools", label="Tool(s)"),
                            TableColumn(
                                field="submissionsToday",
                                label="Records today",
                                align="right",
                                format="int",
                            ),
                            TableColumn(
                                field="flagRate", label="Flag %", align="right", format="percent"
                            ),
                            TableColumn(
                                field="medianTimeLabel", label="Median time", align="right"
                            ),
                            TableColumn(field="whyFlagged", label="Why flagged"),
                        ],
                        sort=SortSpec(field="redFlags", direction="desc"),
                        limit=12,
                        empty_text="No submissions today.",
                    ),
                ],
            ),
            Section(
                id="s14",
                title="1.4 Coverage & trend",
                components=[
                    NarrativeComponent(
                        id="coverage",
                        type="insight",
                        title="Coverage & trend",
                        instruction=(
                            "Describe coverage against plan, naming any lagging tool, say how the "
                            "cumulative flag rate has moved across study days, and give the one "
                            "concrete action for tomorrow."
                        ),
                        data_sources=["tool_coverage", "flag_rate_trend", "study_totals"],
                        fallback="daily_coverage",
                        max_words=180,
                    ),
                    ProgressComponent(
                        id="s14-coverage",
                        title="Coverage vs plan (cumulative)",
                        data_source="tool_coverage",
                        label_field="toolCode",
                        value_field="cumulative",
                        target_field="target",
                        caption="Figure — Cumulative submissions vs study targets by tool.",
                    ),
                    LineChartComponent(
                        id="s14-trend",
                        title="Cumulative flag rate by study day",
                        data_source="flag_rate_trend",
                        x="dayLabel",
                        series=[ChartSeries(field="flaggedPct", label="% flagged", color="teal")],
                        y_label="% flagged (cumulative)",
                        limit=45,
                        caption="Figure — Cumulative flag rate across study days.",
                    ),
                ],
            ),
            Section(
                id="s15",
                title="1.5 Submission quality by enumerator",
                description=(
                    "Look up records by Form and Kobo ID in KoboToolbox under Data then Table."
                ),
                components=[
                    TableComponent(
                        id="s15-quality",
                        data_source="enumerator_submission_quality",
                        columns=[
                            TableColumn(field="enumerator", label="Enumerator"),
                            TableColumn(
                                field="submissionsToday",
                                label="Forms",
                                align="right",
                                format="int",
                            ),
                            TableColumn(
                                field="cleanSubmissions",
                                label="Clean",
                                align="right",
                                format="int",
                            ),
                            TableColumn(
                                field="flaggedSubmissions",
                                label="Flagged",
                                align="right",
                                format="int",
                            ),
                            TableColumn(field="issues", label="DQA issues"),
                        ],
                        sort=SortSpec(field="flaggedSubmissions", direction="desc"),
                        limit=50,
                        empty_text="No submissions today.",
                    ),
                ],
            ),
            Section(
                id="signoff",
                title="Sign-off checklist (read-only)",
                components=[
                    TableComponent(
                        id="signoff-table",
                        data_source="signoff_checklist",
                        columns=[
                            TableColumn(field="severity", label="Severity", format="severity"),
                            TableColumn(field="label", label="Item"),
                            TableColumn(field="detail", label="Detail"),
                            TableColumn(field="owner", label="Owner"),
                        ],
                        limit=40,
                        empty_text="No open checklist items.",
                    ),
                    TextComponent(
                        id="signoff-note",
                        style="note",
                        body=(
                            "This checklist is informational; resolutions are not tracked in-app."
                        ),
                    ),
                ],
            ),
        ],
    )


FINAL_TEMPLATE_PROMPT = """Create the final close-out data quality report for the study.

Title: Final DQA Report.

Open with cumulative KPIs: total submissions, open RED, open AMBER, and the share flagged.
Write an executive summary covering coverage against plan, the leading quality issues, and
what remains before sign-off.

Section 2.2 — Coverage by tool: cumulative submissions against target, plus a progress chart
and the flag-rate trend across study days.

Section 2.3 — Flag summary by tool: submissions, RED, AMBER and percent flagged, with the
rules that failed most often over the study.

Section 2.4 — Findings by tool: one summary row per tool with the leading rule.

Section 2.5 — Enumerator performance across the study: records, flag rate, median time and
the recommended action.

Section 2.6 — Triangulation across tools: study-defined views with mismatch counts and
concordance.

Close with the sign-off checklist of remaining open items."""


def build_final_dqa_spec() -> ReportSpec:
    """The Final DQA report expressed as a specification."""
    return ReportSpec(
        title="Final DQA Report",
        subtitle="Study close-out data quality review",
        sections=[
            Section(
                id="exec",
                title="2.1 Executive summary",
                components=[
                    KpiGroupComponent(
                        id="final-kpis",
                        data_source="study_totals",
                        items=[
                            KpiItem(label="Submissions", field="cumulative", format="int"),
                            KpiItem(label="RED open", field="redOpen", format="int"),
                            KpiItem(label="AMBER open", field="amberOpen", format="int"),
                            KpiItem(
                                label="% flagged", field="flaggedPctCumulative", format="percent"
                            ),
                        ],
                    ),
                    NarrativeComponent(
                        id="headline",
                        type="insight",
                        title="Executive summary",
                        instruction=(
                            "Summarise coverage against plan, the main quality issues, and what "
                            "remains before sign-off. Use only the supplied figures."
                        ),
                        data_sources=["study_totals", "tool_coverage", "findings_by_tool"],
                        fallback="daily_headline",
                        max_words=180,
                    ),
                ],
            ),
            Section(
                id="s22",
                title="2.2 Coverage — by tool",
                components=[
                    TableComponent(
                        id="s22-coverage",
                        data_source="tool_coverage",
                        columns=[
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(field="target", label="Target", align="right", format="int"),
                            TableColumn(
                                field="cumulative", label="Actual", align="right", format="int"
                            ),
                            TableColumn(
                                field="coveragePct", label="% of plan", align="right", format="percent"
                            ),
                        ],
                    ),
                    ProgressComponent(
                        id="s22-progress",
                        title="Coverage vs plan",
                        data_source="tool_coverage",
                        label_field="toolCode",
                        value_field="cumulative",
                        target_field="target",
                        caption="Figure — Actual submissions vs planned targets by tool.",
                    ),
                    LineChartComponent(
                        id="s22-trend",
                        title="Cumulative flag rate",
                        data_source="flag_rate_trend",
                        x="dayLabel",
                        series=[ChartSeries(field="flaggedPct", label="% flagged", color="teal")],
                        caption="Figure — Cumulative flag rate across the collection window.",
                    ),
                ],
            ),
            Section(
                id="s23",
                title="2.3 Data-quality flag summary — by tool",
                components=[
                    TableComponent(
                        id="s23-flags",
                        data_source="tool_coverage",
                        columns=[
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(
                                field="cumulative", label="Submissions", align="right", format="int"
                            ),
                            TableColumn(
                                field="redCumulative", label="RED", align="right", format="int"
                            ),
                            TableColumn(
                                field="amberCumulative", label="AMBER", align="right", format="int"
                            ),
                            TableColumn(
                                field="flaggedPct", label="% flagged", align="right", format="percent"
                            ),
                        ],
                    ),
                    BarChartComponent(
                        id="s23-rules",
                        title="Top failing rules",
                        data_source="top_failing_rules",
                        params={"scope": "cumulative"},
                        x="ruleId",
                        series=[ChartSeries(field="count", label="Records", color="red")],
                        orientation="horizontal",
                        sort=SortSpec(field="count", direction="desc"),
                        limit=8,
                    ),
                ],
            ),
            Section(
                id="s24",
                title="2.4 Findings by tool",
                components=[
                    TableComponent(
                        id="s24-findings",
                        data_source="findings_by_tool",
                        columns=[
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(field="projectName", label="Form"),
                            TableColumn(field="summary", label="Summary"),
                            TableColumn(field="topRule", label="Leading rule"),
                        ],
                        empty_text="No per-tool findings available.",
                    ),
                ],
            ),
            Section(
                id="s25",
                title="2.5 Enumerator performance",
                components=[
                    TableComponent(
                        id="s25-enumerators",
                        data_source="enumerator_performance_study",
                        columns=[
                            TableColumn(field="enumerator", label="Enumerator"),
                            TableColumn(field="tools", label="Tool(s)"),
                            TableColumn(
                                field="submissions", label="Records", align="right", format="int"
                            ),
                            TableColumn(
                                field="flagRate", label="Flag %", align="right", format="percent"
                            ),
                            TableColumn(field="medianTimeLabel", label="Median time", align="right"),
                            TableColumn(field="action", label="Action"),
                        ],
                        sort=SortSpec(field="redFlags", direction="desc"),
                        limit=15,
                    ),
                ],
            ),
            Section(
                id="s26",
                title="2.6 Triangulation across tools",
                components=[
                    TableComponent(
                        id="s26-tri",
                        data_source="triangulation_summary",
                        columns=[
                            TableColumn(field="viewId", label="View"),
                            TableColumn(field="title", label="Title"),
                            TableColumn(
                                field="mismatchCount",
                                label="Mismatches",
                                align="right",
                                format="int",
                            ),
                            TableColumn(
                                field="concordance",
                                label="Concordance",
                                align="right",
                                format="percent",
                            ),
                        ],
                        empty_text="No triangulation views are configured for this study.",
                    ),
                ],
            ),
            Section(
                id="signoff",
                title="2.7 What remains before sign-off",
                components=[
                    TableComponent(
                        id="signoff-table",
                        data_source="signoff_checklist",
                        columns=[
                            TableColumn(field="label", label="Action"),
                            TableColumn(field="toolCode", label="Tool"),
                            TableColumn(field="records", label="Records", align="right", format="int"),
                            TableColumn(field="owner", label="Owner"),
                            TableColumn(field="severity", label="Sev", format="severity"),
                        ],
                        empty_text="No open checklist items.",
                    ),
                    TextComponent(
                        id="signoff-note",
                        style="note",
                        body="This checklist is informational; resolutions are not tracked in-app.",
                    ),
                ],
            ),
        ],
    )


SEED_TEMPLATES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        DAILY_TEMPLATE_ID,
        "DQA Daily",
        "Same-day data quality review used by the Daily report flow. "
        "Studies with no template assigned use this one.",
        "daily",
        DAILY_TEMPLATE_PROMPT,
    ),
    (
        FINAL_TEMPLATE_ID,
        "DQA Final",
        "Study close-out review used by the Final report flow. "
        "Studies with no template assigned use this one.",
        "final",
        FINAL_TEMPLATE_PROMPT,
    ),
)

_SPEC_BUILDERS = {
    DAILY_TEMPLATE_ID: build_daily_dqa_spec,
    FINAL_TEMPLATE_ID: build_final_dqa_spec,
}


def seed_report_templates(db: Session) -> int:
    """Insert or refresh seeded system templates.

    A template edited by a user (its newest version no longer came from the seed) is
    left untouched. Otherwise a changed seed appends a new version so history is kept.
    """
    changed = 0
    for template_id, name, description, kind, prompt_text in SEED_TEMPLATES:
        spec = _SPEC_BUILDERS[template_id]()
        existing = db.get(ReportTemplate, template_id)
        if existing is None:
            create_template(
                db,
                name=name,
                description=description,
                prompt_text=prompt_text,
                spec=spec,
                report_kind=kind,
                source="seed",
                template_id=template_id,
                is_system=True,
                notes="Seeded system template.",
                commit=False,
            )
            changed += 1
            continue

        latest = db.scalars(
            select(ReportTemplateVersion)
            .where(ReportTemplateVersion.template_id == template_id)
            .order_by(ReportTemplateVersion.version.desc())
        ).first()
        if latest is None:
            add_version(
                db,
                existing,
                spec=spec,
                prompt_text=prompt_text,
                source="seed",
                notes="Restored seeded specification.",
                commit=False,
            )
            changed += 1
            continue
        if latest.source != "seed":
            continue
        if latest.spec_json == spec.model_dump(by_alias=True) and latest.prompt_text == prompt_text:
            continue
        add_version(
            db,
            existing,
            spec=spec,
            prompt_text=prompt_text,
            source="seed",
            notes="Updated seeded specification.",
            commit=False,
        )
        changed += 1

    if changed:
        db.commit()
    return changed
