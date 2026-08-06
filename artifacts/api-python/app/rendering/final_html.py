"""Final DQA HTML rendering."""

from __future__ import annotations

from typing import Any

from app.domain.reporting.final_stats import _section_prose as section_prose
from app.rendering import format as fmt
from app.rendering.final_charts import final_chart_pngs

def render_final_html(stats: dict[str, Any]) -> str:
    charts = final_chart_pngs(stats)
    prose = stats.get("sectionProse") or section_prose(stats)
    tot = stats["totals"]
    tools = stats.get("tools") or []

    coverage_table = fmt.html_table(
        ["Tool", "Target", "Actual", "% of plan"],
        [
            [
                t["toolCode"],
                fmt.fmt_int(t["target"]) if t.get("target") else "—",
                fmt.fmt_int(t["cumulative"]),
                fmt.fmt_pct(t["coveragePct"]) if t.get("coveragePct") is not None else "—",
            ]
            for t in tools
        ],
        aligns=["left", "right", "right", "right"],
    )

    flagged_total = sum(int(t.get("flaggedSubmissions") or 0) for t in tools)
    flag_rows = [
        [
            t["toolCode"],
            fmt.fmt_int(t["cumulative"]),
            fmt.fmt_int(t["redCumulative"]),
            fmt.fmt_int(t["amberCumulative"]),
            fmt.fmt_pct(t["flaggedPct"]),
        ]
        for t in tools
    ]
    flag_rows.append(
        [
            "Overall",
            fmt.fmt_int(tot["cumulative"]),
            fmt.fmt_int(tot["redOpen"]),
            fmt.fmt_int(tot["amberOpen"]),
            fmt.fmt_pct(
                round(100.0 * flagged_total / tot["cumulative"], 1)
                if tot.get("cumulative")
                else 0.0
            ),
        ]
    )
    flag_table = fmt.html_table(
        ["Tool", "Submissions", "RED", "AMBER", "% flagged"],
        flag_rows,
        aligns=["left", "right", "right", "right", "right"],
        total_row=True,
    )

    findings_html = []
    for block in stats.get("findingsByTool") or []:
        rules_table = fmt.html_table(
            ["Rule", "Check", "Records", "Sev"],
            [
                [
                    r["ruleId"],
                    r["title"],
                    fmt.fmt_int(r["count"]),
                    fmt.severity_html(r["severity"]),
                ]
                for r in block.get("rules") or []
            ],
            aligns=["left", "left", "right", "center"],
        )
        findings_html.append(
            f"<h3>{fmt.esc(block['toolCode'])} — {fmt.esc(block['projectName'])}</h3>"
            f"<p class='prose'>{fmt.esc(block['summary'])}</p>"
            f"{rules_table}"
        )

    enum_table = fmt.html_table(
        ["Enumerator", "Tool(s)", "Records", "Flag %", "Median time", "Action"],
        [
            [
                e["enumerator"],
                ", ".join(e["tools"]) or "—",
                fmt.fmt_int(e["submissions"]),
                fmt.fmt_pct(e["flagRate"]),
                e.get("medianTimeLabel") or "—",
                e.get("action") or "—",
            ]
            for e in (stats.get("enumeratorsAll") or [])[:15]
        ],
        aligns=["left", "left", "right", "right", "right", "left"],
    )

    signoff_table = fmt.html_table(
        ["Action", "Tool", "Records", "Owner", "Sev"],
        [
            [
                c["label"],
                c.get("toolCode") or "—",
                fmt.fmt_int(c["records"]) if isinstance(c.get("records"), int) else (c.get("records") or "—"),
                c.get("owner") or c.get("ownerHint") or "—",
                fmt.severity_html(c["severity"]),
            ]
            for c in stats.get("signOffChecklist") or []
        ],
        aligns=["left", "left", "right", "left", "center"],
    )

    tool_bits = " · ".join(
        f"{t['toolCode']} {fmt.fmt_int(t['cumulative'])}" for t in tools
    )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{fmt.esc(stats.get('title') or 'Final DQA')}</title>
<style>{fmt.REPORT_CSS}</style></head><body><div class="wrap">
<p class="brand">{fmt.esc(stats.get('organizationName') or 'Infosutra')}</p>
<h1>{fmt.esc(stats.get('title') or 'Final DQA')}</h1>
<div class="meta-grid">
<span class="k">Report</span><span>Final DQA — end of round</span>
<span class="k">Data window</span><span>{fmt.esc(stats.get('reportDateDisplay') or fmt.format_report_date(stats['reportDate']))} (closed)</span>
<span class="k">KoBo pull</span><span>{fmt.esc(stats.get('lastKoboPullDisplay') or fmt.format_report_datetime(stats.get('lastKoboPullAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata', fallback='n/a'))}</span>
<span class="k">Generated</span><span>{fmt.esc(stats.get('generatedAtDisplay') or fmt.format_report_datetime(stats.get('generatedAt'), tz_name=stats.get('timezone') or 'Asia/Kolkata'))}</span>
<span class="k">Total submissions</span><span>{fmt.fmt_int(tot['cumulative'])} ({tool_bits})</span>
</div>
<h2>2.1 Executive summary</h2>
<div class="ai">{fmt.paragraphs_html(stats.get('aiHeadline') or '')}</div>
<h2>2.2 Coverage — by tool</h2>
{fmt.paragraphs_html(prose.get('coverage') or '')}
{coverage_table}
{fmt.img_tag(charts['coverage'], "Coverage vs plan")}
<p class="caption">Figure — Actual submissions vs planned targets by tool.</p>
{fmt.paragraphs_html(prose.get('trend') or '')}
{fmt.img_tag(charts['trend'], "Flag rate trend")}
<p class="caption">Figure — Cumulative flag rate across the collection window.</p>
<h2>2.3 Data-quality flag summary — by tool</h2>
{fmt.paragraphs_html(prose.get('flagSummary') or '')}
{flag_table}
{fmt.img_tag(charts['flagSummary'], "DQA flag summary by tool")}
<p class="caption">Figure 1 — DQA flag summary by tool. Submissions, RED/AMBER counts and % flagged per tool, with overall totals.</p>
{fmt.img_tag(charts['topRules'], "Top failing rules")}
<p class="caption">Figure — Top failing rules (cumulative). Crimson = RED, orange = AMBER.</p>
<h2>2.4 Findings by tool</h2>
{''.join(findings_html) or '<p class="prose">No per-tool findings available.</p>'}
<h2>2.5 Enumerator performance</h2>
<p class="prose">Enumerators ranked by RED volume and flag rate. Median interview/observation time is annotated “(below)” when clearly under the group median.</p>
{enum_table}
<h2>2.6 Triangulation across tools</h2>
{fmt.paragraphs_html(prose.get('tr1') or '')}
{fmt.img_tag(charts['tr1'], "TR-1 claimed vs observed")}
<p class="caption">Figure 2 — TR-1 teacher practice, claimed vs observed. Say–do gap per practice; overall concordance shown on the chart.</p>
{fmt.paragraphs_html(prose.get('triangulationFurther') or '')}
{fmt.img_tag(charts['tr3'], "TR-3 governance")}
<p class="caption">Figure — TR-3 governance concordance (school-reported vs parent-confirmed).</p>
<h2>2.7 What remains before sign-off</h2>
{signoff_table}
{fmt.paragraphs_html(prose.get('signOffClose') or '')}
<p class="note">Infosutra Final DQA · Kobo is source of truth (read-only) · Checklist is informational; resolutions are not tracked in-app.</p>
</div></body></html>"""
