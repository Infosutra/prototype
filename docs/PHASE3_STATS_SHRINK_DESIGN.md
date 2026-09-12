# Phase 3 design: shrink `compute_daily_dqa_stats`

**Status:** audit + design only — no implementation in this step.  
**Date:** 2026-09-06  
**Depends on:** Phase 1 (entity_rows / window) and Phase 2 (certified tools off `ctx.stats()`).

---

## Step 1 — Complete caller audit

### Production builders

| Symbol | Defined | Direct callers |
|---|---|---|
| `compute_daily_dqa_stats` | [`daily_stats.py`](../artifacts/api-python/app/domain/reporting/daily_stats.py) L80 | Only `build_daily_dqa_stats` ([`report_stats.py`](../artifacts/api-python/app/services/report_stats.py) L54). Re-exported from [`domain/reporting/__init__.py`](../artifacts/api-python/app/domain/reporting/__init__.py). |
| `build_daily_dqa_stats` | [`report_stats.py`](../artifacts/api-python/app/services/report_stats.py) L22 | (1) [`ReportDataContext.stats_for`](../artifacts/api-python/app/services/report_tools/context.py) L107; (2) [`build_final_dqa_stats`](../artifacts/api-python/app/services/dqa_final_report.py) L46; (3) golden fixture [`test_report_tools_golden.py`](../artifacts/api-python/tests/test_report_tools_golden.py) L88; (4) **re-export only** from [`dqa_daily_report.py`](../artifacts/api-python/app/services/dqa_daily_report.py) L18/L29 — **not called** by `generate_daily_dqa_report`. |
| `build_final_dqa_stats` | [`dqa_final_report.py`](../artifacts/api-python/app/services/dqa_final_report.py) L36 | [`stats_for`](../artifacts/api-python/app/services/report_tools/context.py) L101–104 when `report_kind == "final"` and default range. |

### Who calls `ctx.stats()` / `stats_for()`

| Caller | Location | Behavior |
|---|---|---|
| `triangulation_summary` | [`sources.py`](../artifacts/api-python/app/services/report_tools/sources.py) L1097 | Reads **only** `stats.get("triangulation")`. |
| `execute_spec` | [`report_execution.py`](../artifacts/api-python/app/services/report_execution.py) L191–205 | **Always** calls `data_context.stats()` and passes the dict to `generate_narratives(..., stats=)` for fallbacks. |
| `stats()` → `stats_for()` | [`context.py`](../artifacts/api-python/app/services/report_tools/context.py) L83–117 | Lazy build: final → `build_final_dqa_stats`; else → `build_daily_dqa_stats`. |
| Test | [`test_query_aggregate.py`](../artifacts/api-python/tests/test_query_aggregate.py) L361/L368 | Identity / memo check only. |

No production code calls `stats_for()` except via `stats()`.

### Indirect chains that force a full collapse

```text
generate_daily_dqa_report  ─┐
generate_final_dqa_report  ─┼─→ execute_template → execute_spec
send_dqa_daily_now / schedule ─┘         │
report_conversations / templates execute ─┘
                                         ├─→ resolve_data / call_tool  (Phase 2 tools; triangulation still on stats)
                                         └─→ data_context.stats()     (FULL daily or final collapse)
                                               └─→ generate_narratives fallbacks
```

Email ([`dqa_daily_email.py`](../artifacts/api-python/app/services/dqa_daily_email.py)) sends persisted HTML/PDF only — **no stats-key reads**.

### Not in the original “known remaining callers” list

| Finding | Why it matters |
|---|---|
| **`execute_spec` always materializes the FULL collapse** | Main cost; happens even when no fallback runs and no triangulation tool is in the spec. |
| **`dqa_daily_report` does not call `build_daily_dqa_stats`** | Known list overstated a *direct* dependency; generate uses template/tools via execute. |
| **Narrative fallbacks** (`daily_headline` / `daily_coverage`) | Real live readers of a **daily subset** of the collapse ([`narratives.py`](../artifacts/api-python/app/domain/reporting/narratives.py); [`report_analyst.py`](../artifacts/api-python/app/services/report_analyst.py) `FALLBACKS`; seeded in [`report_seed_templates.py`](../artifacts/api-python/app/services/report_seed_templates.py)). |
| Orphaned [`dqa_daily_narratives`](../artifacts/api-python/app/services/dqa_daily_narratives.py) (test-only) and dead [`dqa_final_narratives`](../artifacts/api-python/app/services/dqa_final_narratives.py) | Still encode large stats subsets but are not on the live generate path. |
| Final prose helpers in [`final_stats.py`](../artifacts/api-python/app/domain/reporting/final_stats.py) | Live path only uses `enrich_final_checklist`; `_exhaustive_executive_summary` / `_pass_rate` / etc. are test/orphan. |

### Complete inventory vs prior “known” list

| Prior known item | Confirmed? | Nuance |
|---|---|---|
| `triangulation_summary` | Yes | Only certified tool still on `ctx.stats()`. |
| `execute_spec` narrative fallbacks | Yes — **promote to first-class** | Eager `stats()` + `_fallback_*` field reads. |
| `dqa_final_report` | Yes | `build_final_dqa_stats` bases on full daily then adds triangulation / enriches checklist. |
| `dqa_daily_report` / email | Partially | Email/generate **do not** call the builder; they **pay for** it via `execute_spec`. |
| Golden fixture | Yes | Injects full daily build for triangulation `[]` + context. |

**Nothing else** (admin/debug routers) exposes the raw stats dict.

---

## Step 2 — Needs analysis per live consumer

### A. `triangulation_summary` (leave untouched)

- Needs: `triangulation` blob only (final builds).
- Not row-bag aggregation; out of scope for this rework (unchanged classification).

### B. Narrative fallbacks — **subset, live**

| Fallback | Fields used |
|---|---|
| `_fallback_headline` | `totals.newToday`, `totals.redToday`, `dayNumber`, `topRulesToday[]` (`severity`, `ruleId`, `title`, `count`) |
| `_fallback_coverage` | `tools[]` (`toolCode`, `target`, `cumulative`, `coveragePct`), `flagRateByDay[]` (`flaggedPct`, `dayLabel`), `totals.redToday` |

Does **not** need enumerators*, redGrouped, findingsByTool, signOffChecklist, redPriority, enumeratorSubmissionDetails, triangulation, etc.

**Could** be rebuilt from Phase 2 tool outputs already in `execute_spec`’s `data` after `resolve_data` (`study_totals`, `tool_coverage`, `top_failing_rules` today, `flag_rate_trend`, `study_metadata.dayNumber`).

**Risk:** fallbacks speak the **stats-dict** dialect today. Migrating them requires prose parity checks (`test_report_stats`, `test_daily_parity`) — do not silently change wording.

### C. Daily email / `generate_daily_dqa_report`

- Does **not** need the full collapsed shape for its own formatting.
- Uses template execution (Phase 2 tools) + `study_metadata.dayNumber` from tool data for titles.
- Depends on the hub **only** because `execute_spec` eagerly calls `stats()` for fallbacks.

### D. `build_final_dqa_stats`

- Still runs a **full** daily base then attaches triangulation and `enrich_final_checklist(base["signOffChecklist"], triangulation)`.
- Tool data on final templates is already self-served by Phase 2 tools; the daily base is largely redundant for tools.
- **Ambiguity:** checklist enrich currently starts from the collapse’s `signOffChecklist`. Phase 2’s `signoff_checklist` tool recomputes the same recipe independently — final overlay *could* use that recipe instead, but ordering/content must stay identical. Flag as risky for implementers.

### E. Golden fixture

- Can shrink later to `{triangulation: {}}` / empty inject for daily; only final needs a triangulation-bearing blob.

### Keys with no live stats-dict readers (after Phase 2)

Produced by `compute_daily_dqa_stats` but not read via `stats["…"]` on the live path (tools self-serve):  
`enumerators`, `enumeratorSubmissionDetails`, `enumeratorsAll`, `findingsByTool`, `redGrouped`, `redPriority`, `topRulesAll` (except fallbacks use `topRulesToday`), `signOffChecklist` (tool recomputes; final enrich still reads collapse key today), metadata siblings (via `study_metadata` tool), `aiHeadline`/`aiCoverageNote` (always null from compute).

---

## Step 3 — Proposed shrink (recommendation)

### Verdict

**Phase 3 should be “narrow the hub + migrate narrative fallbacks,” not “migrate the daily email as a third product surface.”**

The daily email does not intrinsically need the full collapse. What keeps the hub expensive for daily is eager `execute_spec` → `stats()` for fallbacks. Fix that and email stops paying for free. Keep triangulation / final overlay; do **not** migrate `triangulation_summary`.

### Recommended option: A (smaller, safer, high leverage)

1. **Migrate** `daily_headline` / `daily_coverage` fallbacks onto resolved tool `data` (or thin adapters over Phase 2 recipes). Lock prose parity with existing tests.
2. **Stop eager** `data_context.stats()` in `execute_spec` unless needed (spec contains `triangulation_summary`, `report_kind=="final"`, or transitional fallback still requires it).
3. **Shrink** `compute_daily_dqa_stats`: stop computing slices with no remaining live readers once fallbacks migrate; target end state where **final** path builds triangulation (+ checklist enrich fed from signoff recipe/tool), not a full daily mirror of every former tool.
4. **Leave** `triangulation_summary` and the triangulation engine untouched.
5. **Optional cleanup:** drop unused `build_daily_dqa_stats` re-export from `dqa_daily_report`; remove/quarantine dead `dqa_final_narratives` / unused final prose helpers.

### Rejected / deferred as primary Phase 3

| Option | Why not primary |
|---|---|
| “Migrate daily email onto entity_rows as its own large workstream” | Email already uses template/tools; no separate stats shape to preserve. |
| “Only delete unused keys but keep eager `stats()` + stats-shaped fallbacks” | Leaves the main cost in place. |
| “Rewrite final report fully off a non-daily base in the same pass” | Larger; do after A once checklist/triangulation seams are clear. |

### Open risks (do not auto-resolve in implementation)

1. Fallback prose parity (stats-shaped vs tool-shaped inputs).
2. Final `signOffChecklist` enrich source (collapse field vs Phase 2 recipe) — silent ordering changes.
3. Custom (non-seed) templates that still use `fallback="daily_headline"|"daily_coverage"`.
4. Confirm no hidden consumer relied on the side effect of a warm stats memo after every execute.

### Suggested implementation order (future task)

1. Fallbacks → tool data + parity tests.  
2. Conditional `stats()` in `execute_spec`.  
3. Delete unused collapse slices / slim final builder.  
4. Fixture/test cleanup (golden inject, orphaned narrative modules).

---

## Acceptance for this design step

- [x] Complete caller audit with file/line evidence  
- [x] Needs analysis per remaining consumer  
- [x] Shrink proposal with recommendation and flagged ambiguities  
- [x] No code changes  
