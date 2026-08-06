"""Chart/PNG helpers for DQA Daily & Final reports (matplotlib)."""

from __future__ import annotations

import base64
import io
from typing import Any

# Headless backend before pyplot import.
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

TEAL = "#0f766e"
TEAL_SOFT = "#14b8a6"
STEEL = "#94a3b8"
RED = "#b91c1c"
AMBER = "#d97706"
INK = "#1c1917"
MUTED = "#78716c"
GRID = "#e7e5e4"
CARD_BG = "#fafaf9"


def _fig_to_png(fig: plt.Figure, *, dpi: int = 140) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def png_data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def chart_coverage_vs_plan(tools: list[dict[str, Any]], *, title: str = "Coverage vs plan") -> bytes:
    labels = [t.get("toolCode") or "?" for t in tools]
    actual = [int(t.get("cumulative") or 0) for t in tools]
    target = [int(t.get("target") or 0) for t in tools]
    fig, ax = plt.subplots(figsize=(7.2, 3.4))
    x = range(len(labels))
    width = 0.36
    ax.bar([i - width / 2 for i in x], target, width, label="Target", color=STEEL, edgecolor="none")
    ax.bar([i + width / 2 for i in x], actual, width, label="Actual", color=TEAL, edgecolor="none")
    for i, t in enumerate(tools):
        pct = t.get("coveragePct")
        if pct is not None:
            ax.text(i + width / 2, actual[i] + max(actual + target + [1]) * 0.02, f"{pct}%", ha="center", fontsize=8, color=INK)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Submissions")
    ax.set_title(title, fontsize=11, color=INK, pad=10)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return _fig_to_png(fig)


def chart_flag_rate_trend(series: list[dict[str, Any]], *, title: str = "Flag rate trend") -> bytes:
    """series items: {dayLabel, flaggedPct, newSubmissions?}"""
    if not series:
        fig, ax = plt.subplots(figsize=(7.2, 3.2))
        ax.text(0.5, 0.5, "No trend data yet", ha="center", va="center", color=MUTED)
        ax.axis("off")
        return _fig_to_png(fig)
    labels = [s.get("dayLabel") or s.get("date") or "" for s in series]
    rates = [float(s.get("flaggedPct") or 0) for s in series]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.plot(labels, rates, color=TEAL, marker="o", linewidth=2, markersize=5)
    ax.fill_between(range(len(rates)), rates, color=TEAL, alpha=0.12)
    ax.set_ylabel("% flagged (cumulative)")
    ax.set_title(title, fontsize=11, color=INK, pad=10)
    ax.set_ylim(0, max(15.0, max(rates) * 1.25 if rates else 15))
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    if len(labels) > 8:
        for label in ax.get_xticklabels():
            label.set_rotation(30)
            label.set_ha("right")
    return _fig_to_png(fig)


def chart_today_flags_by_tool(tools: list[dict[str, Any]], *, title: str = "Today's RED / AMBER by tool") -> bytes:
    labels = [t.get("toolCode") or "?" for t in tools]
    red = [int(t.get("redToday") or 0) for t in tools]
    amber = [int(t.get("amberToday") or 0) for t in tools]
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = range(len(labels))
    ax.bar(x, red, label="RED", color=RED, edgecolor="none")
    ax.bar(x, amber, bottom=red, label="AMBER", color=AMBER, edgecolor="none")
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Flags today")
    ax.set_title(title, fontsize=11, color=INK, pad=10)
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return _fig_to_png(fig)


def chart_top_failing_rules(rules: list[dict[str, Any]], *, title: str = "Top failing rules") -> bytes:
    """rules: {ruleId, title, count, severity} — horizontal bars."""
    items = list(rules)[:8]
    if not items:
        fig, ax = plt.subplots(figsize=(5.5, 3.5))
        ax.text(0.5, 0.5, "No flags", ha="center", va="center", color=MUTED)
        ax.axis("off")
        return _fig_to_png(fig)
    items = list(reversed(items))
    labels = [f"{r.get('ruleId')}: {(r.get('title') or '')[:28]}" for r in items]
    counts = [int(r.get("count") or 0) for r in items]
    colors = [RED if str(r.get("severity")).lower() == "red" else AMBER for r in items]
    fig, ax = plt.subplots(figsize=(6.2, max(2.8, 0.42 * len(items) + 1.2)))
    ax.barh(range(len(items)), counts, color=colors, edgecolor="none", height=0.65)
    ax.set_yticks(range(len(items)))
    ax.set_yticklabels(labels, fontsize=8)
    for i, c in enumerate(counts):
        ax.text(c + max(counts) * 0.02, i, str(c), va="center", fontsize=8, color=INK)
    ax.set_xlabel("Records")
    ax.set_title(title, fontsize=11, color=INK, pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_xlim(0, max(counts) * 1.18 if counts else 1)
    return _fig_to_png(fig)


def chart_flag_summary_by_tool(
    tools: list[dict[str, Any]],
    *,
    overall: dict[str, Any] | None = None,
    title: str = "DQA Flag Summary — by tool",
) -> bytes:
    """Figure 1 style: tool cards + overall strip (drawn figure, not CSS)."""
    import textwrap

    fig = plt.figure(figsize=(9.4, 4.6))
    fig.suptitle(title, fontsize=12, color=INK, x=0.02, ha="left", y=0.97)

    card_w = 0.30
    gap = 0.02
    start_x = 0.03
    for i, t in enumerate(tools[:3]):
        ax = fig.add_axes([start_x + i * (card_w + gap), 0.32, card_w, 0.58])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        ax.add_patch(
            FancyBboxPatch(
                (0.02, 0.02),
                0.96,
                0.96,
                boxstyle="round,pad=0.02,rounding_size=0.04",
                facecolor=CARD_BG,
                edgecolor=GRID,
                linewidth=1,
                clip_on=False,
            )
        )
        ax.add_patch(
            plt.Rectangle((0.02, 0.02), 0.03, 0.96, color=TEAL, transform=ax.transData, clip_on=False)
        )

        tool = str(t.get("toolCode") or f"T{i + 1}").upper()
        digit = tool[-1] if tool[-1].isdigit() else str(i + 1)
        raw_name = (t.get("projectName") or "").strip()
        # Prefer a short label after an em/en dash or colon if present
        if "—" in raw_name:
            raw_name = raw_name.split("—")[-1].strip()
        elif " - " in raw_name:
            raw_name = raw_name.split(" - ")[-1].strip()

        subs = int(t.get("cumulative") or 0)
        red = int(t.get("redCumulative") or t.get("redToday") or 0)
        amber = int(t.get("amberCumulative") or t.get("amberToday") or 0)
        flagged_subs = int(t.get("flaggedSubmissions") or 0)
        pct = t.get("flaggedPct")
        if pct is None and subs:
            pct = round(100.0 * flagged_subs / subs, 1) if flagged_subs else 0.0
        pct = pct if pct is not None else 0.0

        def _label(x: float, y: float, s: str, **kwargs):
            ax.text(x, y, s, clip_on=False, **kwargs)

        # Fixed vertical rhythm — tool → name → % → count → sev
        _label(0.10, 0.86, f"Tool {digit}", fontsize=9, color=TEAL, fontweight="bold", va="center")
        name_lines = textwrap.wrap(raw_name, width=24)[:2] if raw_name else []
        y = 0.70
        for line in name_lines:
            _label(0.10, y, line, fontsize=7, color=INK, va="center")
            y -= 0.12
        _label(0.10, max(y - 0.04, 0.42), f"{pct:g}% flagged", fontsize=7.5, color=MUTED, va="center")

        _label(0.10, 0.30, f"{subs:,}", fontsize=17, fontweight="bold", color=INK, va="center")
        _label(0.10, 0.18, "submissions", fontsize=7, color=MUTED, va="center")
        _label(0.10, 0.07, f"{red} RED", fontsize=8, color=RED, fontweight="bold", va="center")
        _label(0.52, 0.07, f"{amber} AMBER", fontsize=8, color=AMBER, fontweight="bold", va="center")

    # Overall strip
    axo = fig.add_axes([0.03, 0.06, 0.92, 0.22])
    axo.set_xlim(0, 1)
    axo.set_ylim(0, 1)
    axo.axis("off")
    axo.add_patch(
        FancyBboxPatch(
            (0.0, 0.05),
            1.0,
            0.9,
            boxstyle="round,pad=0.02,rounding_size=0.04",
            facecolor="#f0fdfa",
            edgecolor=TEAL_SOFT,
            linewidth=1.2,
        )
    )
    o = overall or {}
    total = int(o.get("submissions") or sum(int(t.get("cumulative") or 0) for t in tools))
    red_o = int(o.get("red") or sum(int(t.get("redCumulative") or 0) for t in tools))
    amber_o = int(o.get("amber") or sum(int(t.get("amberCumulative") or 0) for t in tools))
    pct_o = o.get("flaggedPct")
    if pct_o is None:
        flagged = int(o.get("flagged") or 0)
        pct_o = round(100.0 * flagged / total, 1) if total else 0.0
    axo.text(0.03, 0.55, "Overall", fontsize=9, color=TEAL, fontweight="bold", va="center")
    axo.text(0.16, 0.55, f"{total:,}", fontsize=14, fontweight="bold", color=INK, va="center")
    axo.text(0.16, 0.22, "submissions", fontsize=6.5, color=MUTED)
    axo.text(0.38, 0.55, f"{red_o}", fontsize=14, fontweight="bold", color=RED, va="center")
    axo.text(0.38, 0.22, "RED (must fix)", fontsize=6.5, color=MUTED)
    axo.text(0.56, 0.55, f"{amber_o}", fontsize=14, fontweight="bold", color=AMBER, va="center")
    axo.text(0.56, 0.22, "AMBER (verify)", fontsize=6.5, color=MUTED)
    axo.text(0.78, 0.55, f"{pct_o:g}%", fontsize=14, fontweight="bold", color=INK, va="center")
    axo.text(0.78, 0.22, "records flagged", fontsize=6.5, color=MUTED)

    return _fig_to_png(fig, dpi=150)


def chart_tr1_claimed_vs_observed(
    practices: list[dict[str, Any]],
    *,
    concordance_pct: float | None = None,
    title: str | None = None,
) -> bytes:
    """Paired bars with gap annotations for claim_vs_observation views."""
    if not practices:
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.text(0.5, 0.5, "No practice triangulation data", ha="center", va="center", color=MUTED)
        ax.axis("off")
        return _fig_to_png(fig)

    labels = [(p.get("label") or p.get("id") or "")[:22] for p in practices]
    claimed = [float(p.get("claimedPct") or 0) for p in practices]
    observed = [float(p.get("observedPct") or 0) for p in practices]
    gaps = [round(c - o) for c, o in zip(claimed, observed)]
    if concordance_pct is None:
        vals = [float(p.get("concordancePct")) for p in practices if p.get("concordancePct") is not None]
        concordance_pct = round(sum(vals) / len(vals), 0) if vals else round(100 - (sum(abs(g) for g in gaps) / max(1, len(gaps))), 0)

    ttl = title or f"Teacher practice: claimed vs observed · concordance {int(concordance_pct)}%"
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    x = range(len(labels))
    width = 0.36
    ax.bar([i - width / 2 for i in x], claimed, width, label="Teacher self-report", color=TEAL, edgecolor="none")
    bars_obs = ax.bar(
        [i + width / 2 for i in x], observed, width, label="Observed in classroom", color=STEEL, edgecolor="none"
    )
    for i, (bar, gap) in enumerate(zip(bars_obs, gaps)):
        if gap > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 2,
                f"−{gap}",
                ha="center",
                va="bottom",
                fontsize=8,
                color=RED,
                fontweight="bold",
            )
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=8)
    ax.set_ylabel("% of teachers")
    ax.set_ylim(0, 105)
    ax.set_title(ttl, fontsize=11, color=INK, pad=10)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return _fig_to_png(fig)


def chart_governance_mismatch(rows: list[dict[str, Any]], *, title: str = "Cross-form concordance") -> bytes:
    """Simple matched bars: % schools active vs % parents confirming."""
    total = len(rows) or 1
    school_active = sum(1 for r in rows if r.get("schoolGovernanceActive") or r.get("school_governance_active"))
    parent_ok = sum(
        1
        for r in rows
        if (r.get("parentAttendedPta") or r.get("parent_attended_pta"))
        and (r.get("parentCwdIssues") or r.get("parent_cwd_issues"))
    )
    fig, ax = plt.subplots(figsize=(6.5, 3.0))
    labels = ["School reports\nactive PTA+CWD", "Parents confirm\nattend + CWD issues"]
    vals = [100.0 * school_active / total, 100.0 * parent_ok / total]
    colors = [TEAL, STEEL]
    ax.bar(labels, vals, color=colors, edgecolor="none", width=0.55)
    for i, v in enumerate(vals):
        ax.text(i, v + 2, f"{v:.0f}%", ha="center", fontsize=9, color=INK)
    ax.set_ylim(0, 110)
    ax.set_ylabel("% of institutions")
    ax.set_title(title, fontsize=11, color=INK, pad=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return _fig_to_png(fig)
