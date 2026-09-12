# Phase 4 design: `dateWindow` on cumulative certified tools

**Status:** design only — no implementation in this step.  
**Date:** 2026-09-06  
**Depends on:** Phase 1 (`window` / `entity_rows`), Phase 2 (tools off `ctx.stats()`), Phase 3 (hub shrink; not required for this design).  
**Original one-liner:** let cumulative-shaped certified tools accept an explicit `dateWindow`, using the P0 two-flag descriptor system (`supports_date_window`, `execution_day_scoped`).

---

## 0. Current baseline (facts)

| Flag / list | Today’s live set |
|---|---|
| `supports_date_window=True` | `query_aggregate` only |
| `execution_day_scoped=True` | `enumerator_performance_today`, `enumerator_submission_quality` |
| `unsafeForMultiDayOrEntireRange` | Those two only (`execution_day_scoped ∧ ¬supports_date_window`) |
| `dateWindowCapable` | `["query_aggregate"]` |

Cumulative candidates (`enumerator_performance_study`, `findings_by_tool`, `flag_rate_trend`, `top_failing_rules`, `study_totals`, `tool_coverage`) are **already absent** from the unsafe list because they are **not** `execution_day_scoped`. The planner may already treat them as “cumulative default-bag” answers for multi-day asks — but they always load `window("study_to_date")`, so a “last 14 days” ask answered with `enumerator_performance_study` today is **silently full-study**, not windowed. Phase 4’s job is to make an explicit token actually narrow the bag.

**Omit-default note (important):**  
- `query_aggregate` omit → execution **context** range (`date_from`/`date_to`, often unbounded).  
- Phase 2 certified cumulatives omit → hardcoded **`study_to_date`**.  
Phase 4 must keep that certified default (`study_to_date` when `dateWindow` omitted) so goldens and Daily templates stay byte-stable. Do **not** silently align omit with query_aggregate’s context-bag semantics.

---

## 1. Out of scope (confirmed)

### Always execution-day only — leave flags alone

| Tool | Why |
|---|---|
| `enumerator_performance_today` | Already `execution_day_scoped=True`; window is `execution_date` only. |
| `enumerator_submission_quality` | Same. |
| `top_failing_rules` with `scope=today` (or omitted scope → today) | Must stay pinned to `execution_date`. |

### `red_priority_items` — keep out (reasoning **confirmed**)

`apply_red_priority_items(today_groups, all_groups, …)` **prefers today’s RED groups; else falls back to cumulative**. The tool loads both `execution_date` and `study_to_date` bags and feeds that certified fallback.

A caller-supplied `dateWindow` would either:

- replace both halves (destroying the today-vs-cumulative fallback), or  
- apply only to the cumulative half (leaving “today” fixed while “fallback cumulative” means something other than study-to-date — a new, uncertified hybrid).

Neither matches the domain rule as written. **`supports_date_window` stays False; no `dateWindow` param.**

---

## 2. Per-candidate design

### Shared param shape (all confirmed tools)

Mirror `query_aggregate`’s param (same allowlist / validation):

```text
DataSourceParam(
  name="dateWindow",
  type="string",
  required=False,
  allowed=sorted(DATE_WINDOW_TOKENS),  # execution_date | last_7_days | last_14_days | study_to_date
  description="… Omit to use study_to_date (certified default)."
)
```

**Runtime default when omitted:** `ctx.window("study_to_date")` — identical to today’s Phase 2 hardcode.  
**When set:** `ctx.window(params["dateWindow"])` (then clamp to context range if set — already in `resolve_query_date_window`).

Goldens bind no params → omit → unchanged outputs.

---

### A. `enumerator_performance_study` — **include**

| # | Decision |
|---|---|
| 1. Param | Add `dateWindow`; omit → `study_to_date`. Set `supports_date_window=True`. Keep `execution_day_scoped=False`. |
| 2. `domain_rules` | `apply_enumerator_performance_study` thresholds (`flag_pct_threshold=12`, `below_ratio=0.85`, top-25) are **relative to the supplied row bag** — no hard-coded “full study” assumption in the math. **Label/copy coupling:** descriptor title/description/`groupFlagRate` field say “Study flag %” / “full study window” / “all enumerators in the study.” Narrower windows make those strings misleading. **Implementers must** soften catalog copy (e.g. “window flag %”, “enumerators in range”) when adding the param — **do not change** `apply_*` thresholds. |
| 3. Composite? | N/A — single cumulative window. |
| 4. Flags | `supports_date_window=True`; add `dateWindow` param. |
| 5. Planner | Catalog-driven: appears in `dateWindowCapable` + params list automatically. Soften `business_definition` so omit still means study-to-date. |

---

### B. `findings_by_tool` — **include**

| # | Decision |
|---|---|
| 1. Param | Same as A. |
| 2. `domain_rules` | `apply_findings_by_tool` builds English from counts only (`"Led by AMBER … (N records)"`) — **no “to date” / “study” wording** in narratives. Field names `redCumulative` / `amberCumulative` mean “within the loaded bag,” not calendar-to-date. Safe without `apply_*` changes. Soften descriptor `business_definition` (“Counts are cumulative”) → “Counts are over the selected window (default: study to date).” |
| 3–5 | Same pattern as A. |

---

### C. `flag_rate_trend` — **MURKY — do not implement until decided**

| # | Issue |
|---|---|
| Current recipe | Loads `study_to_date` bag; `build_flag_rate_by_day(..., study_start_date=study.start, date_key=context.execution_date)` walks **every study day from start → execution_date**, computing cumulative flag % using rows in the bag. |
| If `dateWindow=last_14_days` naïvely | Bag only has ~14 days of rows, but the walker still starts at **study start**. Early day labels (D1…) show **0 submissions** until the window; late days look like a truncated cumulative. Day labels stay anchored to study start. That is **not** an obvious “last-14-days trend.” |
| Alternatives (need product pick) | **(C1)** Window only filters the bag; series still study-start→execution_date (weird zeros). **(C2)** Re-anchor series to `max(study_start, window_from)` → `window_to` / execution_date, relabel days. **(C3)** Exclude from Phase 4; keep using `query_aggregate` + certified full-study trend only. |
| `domain_rules` | No `apply_*`; coupling is in `build_flag_rate_by_day` + field caption “% flagged (cumulative)”. |

**Recommendation for implementers:** treat as **excluded pending decision** (prefer **C3** or **C2** explicitly — do not ship C1 silently).

---

### D. `top_failing_rules` — **MURKY (param interaction) — design partial, flag before coding**

| # | Issue |
|---|---|
| Current | `scope=cumulative` → `study_to_date`; `scope=today` / omit → `execution_date`. |
| Desire | `dateWindow` only for cumulative; today stays pinned. |
| Flag model tension | `supports_date_window` is **per descriptor**, not per scope. Flipping True puts the **whole** tool in `dateWindowCapable`, including when the planner emits `scope=today`. Unsafe list still won’t include it (`execution_day_scoped` is False on the descriptor). Guard prose already special-cases `scope=today` as execution-day scoped — that prose must stay / be strengthened. |
| Validation need | Reject or ignore `dateWindow` when `scope=today` (prefer **reject** with a clear `param_conflict` so planners don’t think the window applied). |
| `domain_rules` | `apply_top_failing_rules` = severity coerce + top-12; **no study-wide wording**. Safe. |
| Default | omit `dateWindow` + `scope=cumulative` → `study_to_date` (unchanged). |

**Open decision for you:**  

- **(D1)** Add `dateWindow`, `supports_date_window=True`, validate conflict with `scope=today`.  
- **(D2)** Split into two catalog ids (today vs cumulative) — larger change, cleaner flags.  
- **(D3)** Defer; only allow windowed rule rankings via `query_aggregate`.

Do **not** implement until D1/D2/D3 is chosen.

---

### E. `study_totals` / `tool_coverage` — **exclude from Phase 4 (recommended)**

| # | Analysis |
|---|---|
| Shape | Dual-window composites: `execution_date` (“today”) + `study_to_date` (“cumulative” / coverage vs **full-study target**). |
| If `dateWindow` only on cumulative half | One card shows **today = execution day** beside **cumulative = last_14_days** (and `coveragePct` / `remaining` still vs **full study target**). Easy to read as “study progress” when it is not. |
| If `dateWindow` applied to both | Breaks Daily “today” semantics and `execution_day_scoped` product meaning. |
| Coherence | **Not coherent** without renaming fields (`cumulative` → `inWindow`, retargeting coverage, or splitting sources). |

**Decision to confirm:** **exclude** both from Phase 4. Multi-day intake/coverage asks stay on `query_aggregate` (or a future dedicated non-composite tool). Leave `supports_date_window=False`.

---

## 3. Validation / catalog changes

1. **Per included tool:** add `dateWindow` param + `supports_date_window=True` (same `DATE_WINDOW_TOKENS` allowlist as `query_aggregate`).  
2. **`_check_distinct_date_ranges`** ([`validation.py`](../artifacts/api-python/app/domain/report_spec/validation.py)): today every non-`query_aggregate` source contributes `DEFAULT_RANGE_TOKEN`. **Must** treat any `supports_date_window` source like `query_aggregate` — use `semantic_date_range_token(params.dateWindow)` (omit → need a token that means **certified study_to_date default**, not query_aggregate’s context-bag default — see open point below).  
3. **Omit-token identity:** Option A (recommended): omit on certified tools maps to semantic token `"study_to_date"` for range-counting (matches runtime). Option B: introduce `"certified_default"` alias equal to study_to_date for counting only. Do **not** map certified omit to `"default"` (context bag) or goldens/Daily + one `last_14_days` QA could be mis-counted.  
4. **`top_failing_rules` (if D1):** reject `dateWindow` + `scope=today`.  
5. **No change** to Stage-2 max of 2 distinct ranges.

---

## 4. Planner prompt / few-shots (catalog-driven)

Already injected every plan request:

- Per-source `supportsDateWindow` / `executionDayScoped`  
- `temporalMismatchGuard.dateWindowCapable` / `unsafeForMultiDayOrEntireRange` / `withoutDateWindow`

**After flag flips, capable list updates automatically** — no hand-maintained id list required for the guard payload.

Still update **seeded planner prose** ([`report_planner_prompts.py`](../artifacts/api-python/app/services/report_planner_prompts.py)) where it hardcodes “today: query_aggregate”:

- Say dateWindowCapable includes listed cumulative tools (or “see temporalMismatchGuard.dateWindowCapable”).  
- Few-shot: e.g. “enumerator performance last 14 days” → `enumerator_performance_study` + `dateWindow=last_14_days` (not only `query_aggregate`).  
- Keep anti-pattern: never bind `enumerator_performance_today` / `enumerator_submission_quality` for multi-day.  
- Keep `top_failing_rules` scope=today warning regardless of `supports_date_window`.

---

## 5. Temporal-mismatch / flip-flag test — **run for real**

`tests/test_report_planner.py::test_temporal_mismatch_guard_is_descriptor_driven` — **PASSED** (2026-09-06).

What it proves:

- Unsafe list is computed from flags, not a hardcoded constant.  
- Flipping `supports_date_window=True` on an `execution_day_scoped` tool (`enumerator_submission_quality`) **removes it from** `unsafeForMultiDayOrEntireRange`.

What Phase 4 flips on **cumulative** tools actually do:

| Effect | Result of flipping candidates |
|---|---|
| `unsafeForMultiDayOrEntireRange` | **Unchanged** (candidates are not `execution_day_scoped`) |
| `dateWindowCapable` | Grows to include those ids (verified by simulation) |

So the flip-flag test **does** prove the metadata mechanism; for Phase 4 candidates the user-visible win is **joining `dateWindowCapable`**, not leaving the unsafe list (they were never on it). Implementers should **extend** the test (or add a sibling) asserting e.g. `enumerator_performance_study` appears in `dateWindowCapable` after the real flag flip — the existing test’s loop that asserts “all non-QA tools have `supports_date_window is False`” **will need updating** when Phase 4 lands.

---

## 6. Proposed Phase 4 scope (pending your calls)

| Tool | Verdict |
|---|---|
| `enumerator_performance_study` | **In** — param + flag + copy soften |
| `findings_by_tool` | **In** — param + flag + copy soften |
| `flag_rate_trend` | **Out** — permanently study_to_date only (re-anchoring would redefine certified cumulative) |
| `top_failing_rules` | **In** — `dateWindow` only with `scope=cumulative` (validation rejects otherwise); `supports_date_window=True` |
| `study_totals`, `tool_coverage` | **Out** — composite coherence |
| Today-scoped tools + `red_priority_items` | **Out** — confirmed |

**Implemented 2026-09-06** with those decisions.
---

## 7. Acceptance criteria for a future implementation pass

- [ ] Omitted `dateWindow` → byte-identical to current goldens (`test_report_tools_golden.py` unmodified).  
- [ ] Explicit `last_7_days` / `last_14_days` narrows bags for included tools; covered by new tests.  
- [ ] `temporalMismatchGuard.dateWindowCapable` lists included tools; planner prompt no longer says “capable = query_aggregate only.”  
- [ ] Distinct-range validation counts certified `dateWindow` tokens correctly.  
- [ ] No changes to `domain_rules.apply_*` thresholds unless a held tool’s decision requires it.  
- [ ] Held / excluded tools unchanged.
