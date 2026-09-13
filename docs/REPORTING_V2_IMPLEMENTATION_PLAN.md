# Reporting rewrite — implementation plan (for Cursor Auto)

You are implementing a **rewrite** of Infosutra reporting. This document is the spec.
Do not invent a parallel design. Do not preserve the intern catalog “for
compatibility.” Break reporting if needed; delete baggage; fix forward.

Repo: `Data-Insights-Hub/`
API: `artifacts/api-python/`
UI: `artifacts/infosutra/`
Generated client: `pnpm run api:client` (updates `lib/api-spec/openapi.yaml` + `lib/api-client-react`)

Run tests from `artifacts/api-python`: `uv run pytest -q`
After any public API change: `pnpm run api:client` from repo root, then `pnpm run typecheck`.

```
<!-- PHASE_STATUS: phase 5 done; all phases done -->
```

---

## 0. Agent operating rules

1. **One engine.** A component binds to a Query IR, never to a named report tool
   (`enumerator_performance_today`, `study_totals`, `signoff_checklist`, …).
2. **HTTP is thin.** Routers enqueue jobs or do cheap CRUD. Routers must not call
   the LLM, the query compiler, or PDF rendering inline.
3. **SQL, not Python bags.** Production aggregation is compiled SQL. Do not load
   all study submissions into memory to group them. Do not JSON-extract
   `submissions.data` at report time for aggregates.
4. **LLM never invents numbers.** Planner outputs spec JSON only. Narrative LLM
   sees already-fetched datasets only. The LLM must not invent rate formulas.
5. **No dual data plane.** Do not add a new certified tool. Do not teach the
   planner a menu of report recipes. Do not keep `query_aggregate` as a “tool”
   beside the query engine — the query engine *is* the only data plane.
6. **Hard cut — break and fix.** Signed off: it is OK to break reporting (and
   related UI) to get a clean reporting stack. Do **not** carry dual paths, adapters, or
   “keep legacy reporting compiling until Phase 5” scaffolding. When schema or contracts
   conflict with old code, **delete or stub the old path** and fix callers.
   DQA evaluation, Kobo sync, and non-report product surfaces should keep
   working; reporting is the sacrifice zone.
7. **Stop at phase gates.** Do not start phase N+1 until phase N exit criteria
   (commands below) pass. If a gate fails, fix it; do not weaken the gate.
8. **Prefer deleting code** over wrapping it. Delete legacy reporting modules as
   soon as they are unused or broken by the new schema — do not park dead code
   for a late phase. Phase 5 is a **final grep sweep**, not the first deletion.
9. **Jobs are the only async lifecycle store.** Table `jobs` + result files. Do
   **not** create or keep `ReportRun`. Put tokens/latency inside the result
   artifact JSON (or slim job metrics columns) if needed. Do not invent a third
   observability table.
10. **No system / seed report templates.** There is no shipped Daily or Final
    layout. Users author templates (Create template / Compose) before they can
    run or schedule a report. Do not call `seed_report_templates` on boot.
    Do not keep `is_system` columns or fallbacks that invent a report the user
    never saved. Dropped in the Phase 0 schema baseline.
    **Exception:** LLM *system prompts* (planner/judge/analyst) **are** seeded
    into `prompts` and shown in the Prompts UI — that is config, not a report
    layout.
11. **Wipe-friendly schema.** Prototype data may be destroyed. Prefer one fresh
    Alembic baseline (or drop DB + recreate) over a long alter chain. Keep
    `submissions.data` as the raw Kobo archive for DQA/UI; never use it for
    report aggregates once answers/quality exist.
12. **No baggage.** Do not add shims, compatibility flags, dual validators, or
    “temporary” seed fallbacks. If a test asserts legacy tool/seed behavior, rewrite
    or delete the test in the same phase that removes the code.
13. **No V1/V2 in code names.** This rewrite is greenfield naming. Use
    `ReportSpec`, `app/domain/reporting/`, `app/services/reporting/`,
    `tests/test_reporting_*`. Do **not** create `ReportSpecV2`, `reporting_v2`,
    or `specVersion: "2.0"` as a monument to migration history. Schema field
    `specVersion: "1.0"` means the first version of *this* schema. Docs may say
    “rewrite”; identifiers must not.

### Three design gates (must hold after phase 5; enforce as you go)

| # | Gate | How you prove it |
|---|---|---|
| G1 | A legal aggregate over known columns ships with **zero new Python** | Golden spec in tests; no new handler file |
| G2 | HTTP handlers do **not** call LLM or query engine inline | Grep routers; tests that POST returns 202 before work finishes |
| G3 | A new survey field is **ingest + catalog**, not a new handler | Answers table + catalog test; no `sources.py` entry |

---

## 1. Product flow (do not confuse these two moments)

```
AUTHORING (Create template + Compose — same backend)
  English → POST /jobs {type:plan} → 202 jobId
  → worker: schema catalog + system prompt + LLM → ReportSpec JSON
  → validator → judge
  → GET /jobs/:id  { spec, unmapped[], judgement }
  → UI: section cards (structure only, NO numbers)
  → user saves template (save path, no LLM)

EXECUTION (Reports list, and Preview on authoring screens)
  template + window → POST /jobs {type:execute} → 202 jobId
  → worker: QueryEngine SQL → datasets → optional narrative LLM
  → ExecuteResult JSON **file** (+ PDF on disk) → job `result_ref`
  → GET /jobs/{id} hydrates `result` → UI tables/charts/KPIs (this is preview)
```

- **Section cards** = review of the spec (phase 4 UI). Not preview.
- **Preview** = execute job filled with data. Canonical = **ExecuteResult JSON file**;
  API returns it hydrated on `GET /jobs/{id}`.
  Live UI today uses server HTML iframes; HTML/PDF must be pure functions of that
  JSON. Do not center work on unused `SpecPreview.tsx` unless you wire it as the
  JSON renderer.
- Create template = one `plan` then save.
- Compose = repeated `plan` with `currentSpec` (patch). Same job type.
- `/reports` = pick a **user-saved** template and run it (execute job). There is
  no one-click “Generate Daily/Final” that implies a built-in layout. Until a
  study has at least one saved template (or an assigned template id), Generate /
  schedule stay disabled with a clear CTA to author one.

---

## 2. What legacy reporting was (delete — do not extend or preserve)

Old intern stack — **reference only**. Do not add features. Delete as soon as
the phase that replaces it lands (or earlier if the schema already breaks it):

- Certified tools: `app/services/report_tools/sources.py` (~12 named sources)
- In-memory bags: `app/domain/reporting/entity_rows.py`, `aggregate.py`, plus
  `app/services/report_tools/query_aggregate.py`
- LangGraph planner: `app/services/report_planner/`
- Inline plan/execute in routers: `app/routers/report_templates.py`,
  `report_conversations.py`, `reports.py`
- Orchestrators: `dqa_daily_report.py`, `dqa_final_report.py`, `daily_report.py`
- Legacy spec: `app/domain/report_spec/` with `data_source: "study_totals"` etc.
- Telemetry: `ReportRun` — **deleted in Phase 0** (do not reintroduce)
- Preview via `execute_spec` / `generated_content` — **deleted in Phase 0**;
  replaced by job `result_ref` + hydrate on read

**Prototype wipe (signed off):** Local SQLite / report artifact files may be
deleted. Do not write data-migration scripts for old reports, seeds, or
`ReportRun` rows.

**Break-and-fix policy (signed off):**

- It is acceptable for Generate / Preview / Compose / schedule email to be
  **down or empty-state** between Phase 0 and the phase that restores that
  surface on the new stack.
- Do **not** keep a parallel legacy reporting path “so demos still work.”
- When a deleted column/module breaks imports: delete the caller or retarget it
  to the new modules — never restore the old column “for compatibility.”
- Keep Kobo sync + DQA **evaluation** working (dual-write projections). Fix
  those call sites carefully; do not break flag evaluation to rush reporting.
- Rewrite or delete tests that require seeds, `ReportRun`, `sources.py`, or
  `generated_content` in the same change set.

New work lives in `reporting` / `jobs` only.

---

## 3. Target contracts (frozen — implement exactly)

### 3.0 Schema baseline (wipe-friendly — implement in Phase 0)

Current schema is project-scoped and JSON-blob–centric. Target schema is
**study-scoped SQL facts + jobs lifecycle + file refs for large outputs**.

**Strategy:** wipe prototype DB → one Alembic revision that matches the models
below (squash/replace old migrations if easier than altering). Re-sync Kobo and
re-run DQA after wipe; do not backfill production history (there is none that
matters).

#### Keep (core domains)

| Area | Tables | Notes |
|---|---|---|
| Study | `studies`, `study_credentials`, `study_tools` | Keep. Remove seed-template FK fallbacks (see Drop). |
| Kobo | `projects`, `submissions` | Keep `form_definition` and `submissions.data` as **raw archive**. |
| DQA | `dqa_flags`, `rule_packs`, `rule_pack_versions`, `dqa_relationships`, `dqa_compile_sessions`, `triangulation_views` | Keep; triangulation stays a DQA UI feature, not a report tool. |
| Authoring | `report_templates`, `report_template_versions`, `report_conversations`, `report_conversation_messages` | Keep; reshape nullability / drop `is_system`. |
| Outputs | `reports`, `report_projects`, `report_schedules` | Keep; `reports` uses `result_ref`, not blob-as-truth. |
| Other | `prompts`, `settings`, `audio_recordings`, `usage_events`, `insights` | Keep SMTP/AI/transcription. Drop legacy daily_* from settings. `insights` optional; leave unless it blocks boots. |

#### Add

| Table / columns | Purpose |
|---|---|
| `jobs` | §3.1 — lifecycle only; `result_ref` to file |
| `submission_answers` | §3.2 — typed answers for Query IR entity `answer` |
| `submission_quality` | §3.2 — `is_clean` + severity counts |
| `submissions.duration_minutes`, `submissions.calendar_day` | SQL measures / `groupBy day` |
| `submissions.study_id` | Denormalized from `project.study_id` at upsert (nullable only when project has no study; Query IR filters `study_id = :id`) |
| `dqa_flags.study_id` | Same denormalization at flag write / eval |
| `reports.result_ref` | Path/key to ExecuteResult JSON file (canonical) |
| Indexes | `(submissions.study_id, calendar_day)`, answers `(study_id, field_key)`, jobs `(status, created_at)` |

Empty answers/quality tables are created in Phase 0; **writers** land in Phase 1.

#### Reshape (ownership)

| Change | Rule |
|---|---|
| `report_templates.study_id` | **NOT NULL** — every template is study-owned |
| `report_schedules.template_id` | **NOT NULL** — no schedule without an explicit template |
| `reports.study_id` | **NOT NULL** on new writes |
| `report_templates.current_version_id` | Prefer real FK to `report_template_versions.id` (nullable until first version) |
| `report_kind` / window labels | May remain as user labels (`daily` / `final` / `adhoc`); **not** seed loaders |
| `Study.daily_report_template_id` / `final_report_template_id` | Optional **user assignment** only — never resolve to `seed-dqa-*`. Or drop both and use template picker + schedule `template_id` only (preferred if UI is updated in Phase 0/5) |

#### Drop (do not recreate)

| Item | Why |
|---|---|
| `report_runs` / `ReportRun` model | Replaced by `jobs` |
| `report_templates.is_system` | No system templates |
| Seed rows / `source='seed'` as a privileged path | Users author templates |
| `reports.generated_content` as canonical blob | Use `result_ref` + file; do not keep dual truth |
| `AppSettings.daily_report_*` columns | Schedules live in `report_schedules` |
| Lifespan `seed_report_templates` | Boot must not insert layouts |

**Do not drop** `submissions.data` — DQA eval and submission detail UI still need the raw payload. The smell was **aggregating from it at report time**.

### 3.1 Job record

Table `jobs` holds **lifecycle metadata only**. Large outputs live on disk
(same idea as today’s PDF/DOCX under `app/services/report_storage.py`). Works
the same on SQLite prototype and a later production DB.

| column | type | notes |
|---|---|---|
| id | str PK | returned as jobId |
| type | str | `plan` \| `execute` \| `email` \| (later: `kobo_sync`, `dqa_eval`) |
| status | str | `pending` \| `processing` \| `completed` \| `failed` |
| study_id | str \| null | |
| payload | JSON | input; keep small; never include secrets |
| result_ref | str \| null | storage key / relative path to result JSON file; not the blob |
| error | text \| null | domain message, never raw SQL/LLM dumps |
| created_at, updated_at, started_at, finished_at | datetime | |
| expires_at | datetime \| null | from `job_plan_result_ttl_hours` (suggested 24h) for plan; delete file on expire |

**Result storage (required):**

- On `complete`, write PlanResult / ExecuteResult JSON to a file under the
  reports/jobs data dir (extend `report_storage` or add
  `app/services/jobs/artifacts.py`). Set `result_ref` to that path/key.
- On `fail`, set `error`; leave `result_ref` null (do not write a result file).
- PDF bytes stay on disk (existing `pdf_path_for`); ExecuteResult
  `artifacts.pdf` is a URL/path, not embedded PDF bytes in the JSON.
- Do **not** store PlanResult / ExecuteResult JSON columns in SQLite/Postgres.
  DB ports and backups stay lean; swapping DBs does not move multi‑MB blobs.

API (client contract — one round trip for the result):

- `POST /jobs` body `{ type, studyId, payload }` → **202** `{ jobId }`
- `GET /jobs/{jobId}` → `{ jobId, type, status, result?, error? }`
  - Server **reads `result_ref` and hydrates** `result` from the file before
    responding. The client never sees `result_ref` and does **not** make a
    second call for the JSON.
  - Pending/processing: omit `result`. Failed: omit `result`, include `error`.
  - Missing/corrupt result file on a completed job → treat as failed domain
    error (or 500 with a safe message); do not return a bare ref.
- Tenant/study: job is scoped to `studyId`; GET 404 if missing.

Worker: in-process loop (extend or replace `app/main.py` lifespan scheduler).
SQLite is fine for the **jobs table**. **Do not add Redis/Celery.**

**Claim strategy (required):** single-process
`UPDATE … WHERE status='pending'` (or equivalent) then run handler. Document in
`app/services/jobs/store.py`. Time-slice / budget so a long `execute` does not
starve the existing lifespan Kobo/email tick (same loop with a per-tick claim
budget is fine).

**Router test (G2):** `POST /jobs` returns 202 while a slow handler is patched
to sleep; status is still `pending` or `processing` on immediate GET.

### 3.2 Ingest tables and denormalized facts

**Study scope (required):** denormalize `study_id` onto `submissions` and
`dqa_flags` at write time (from `project.study_id`). Projections
(`submission_answers`, `submission_quality`) also carry `study_id`. Skip answer /
quality writes when `study_id` is null. Query IR always filters
`study_id = :studyId` (no “all projects on earth” scans).

**Reassignment rule (required):** when a project’s `study_id` changes (assign,
move, or unassign in `app/services/studies.py`), rewrite `study_id` on that
project’s `submissions`, `dqa_flags`, `submission_answers`, and
`submission_quality` in the same transaction — or delete projections and let
the next sync/eval rebuild them. Do not leave stale study ids after
`project.study_id = None` / reassign. Prototype wipe does not remove this rule;
tests must cover assign → sync → reassign.

`toolCode` comes from `StudyTool` via `projects.study_tool_id` join — not a
column on submissions unless you later denormalize it for convenience (optional;
join is fine for the first cut of the engine).

**`submission_answers`** (written on Kobo upsert, deleted with submission):

- `id`, `submission_id` FK, `project_id`, `study_id` (**mandatory**, from
  `project.study_id` at write; skip write if study_id is null)
- `field_key` (stable Kobo path), `field_label`
- `value_type`: `string` \| `number` \| `boolean` \| `datetime`
- `value_text`, `value_number`, `value_bool`, `value_datetime` (only one populated)
- Unique `(submission_id, field_key)`
- Indexes: `(study_id, field_key)`, `(study_id, submission_id)`

Skip metadata keys: `_id`, `_uuid`, `_notes`, `_attachments`, and other Kobo meta.
**`start` / `end` are duration sources only — do not store them as answer rows.**
Project scalar answers from `Submission.data` using existing helpers
(`app/services/form_labels.py`, `app/domain/dqa/form_fields.py::list_form_fields`)
and `Project.form_definition` labels when present. Do not invent a new survey walker.

**`submission_quality`** (upserted when DQA flags for that submission change):

- `submission_id` PK/FK, `study_id`, `project_id`
- `is_clean` bool — **true iff the submission has zero DQA flags**
- `max_severity` — `null` \| `amber` \| `red` (red wins)
- `flag_count` int
- `red_count`, `amber_count` int
- `updated_at`

Definition of clean is this table, not a comment in a tool. Tests lock it.

**Also denormalize at sync time (required for SQL measures / groupBy day):**

- `submissions.study_id` (nullable only if project unassigned)
- `submissions.duration_minutes` (nullable int/float) from `data["start"]` /
  `data["end"]` using the same rules as `app/domain/reporting/helpers.py::duration_minutes`
- `submissions.calendar_day` (date, study TZ) for `groupBy: day`. Do **not** rely
  on SQLite IANA timezone functions at query time.
- `dqa_flags.study_id` at flag write
- Flags use the joined submission’s `submitted_at` / `calendar_day` (same as v1
  entity_rows: never `evaluated_at` for the reporting clock).

Without these columns, Query IR `avg`/`sum` of duration and `groupBy: day` will
cheat with JSON extraction or fail G1.

**Hook points (dual-write, do not break existing sync/eval):**

- **Answers + duration + calendar_day + study_id:** after each submission upsert
  flush in `app/services/kobo_sync.py` (touched set), call
  `replace_answers_for_submission` and update duration/calendar_day/`study_id`
  on the row.
- **Quality:** after `evaluate_submission` returns (including empty pack / zero
  flags → `is_clean=true`), and after `evaluate_project` batch commit for **all**
  evaluated ids (not only those that produced flags). Cover cascade call sites too.
  Ensure flag rows get `study_id`.
- On prune/`delete(Submission)`, rely on FK CASCADE from `submission_answers` /
  `submission_quality` — test it.
- After wipe, Phase 1 writers + re-sync replace any “backfill existing DB”
  script. Keep a small backfill helper only for tests that insert rows without
  going through sync.

### 3.3 Query IR

Pydantic models in `app/domain/reporting/query.py` (names may vary; shape must match):

```text
Query
  entity: "submission" | "flag" | "answer"
  window: "execution_date" | "last_7_days" | "last_14_days" | "study_to_date"
  groupBy: list[str]          # max length from config (below); must be in entity dimensions
  measures: list[Measure]     # min 1 for aggregates; omit for row lists
  filters: list[Filter]       # field, op, value
  limit: int                  # per-query row cap; default + ceiling from config (below)
  sort: { field, dir }?

Measure
  id: str                     # output column name
  fn: "count" | "countDistinct" | "countWhere" | "sum" | "avg" | "min" | "max"
  field?: str                 # required except count
  eq?: bool | str | number    # for countWhere (e.g. isClean eq true)

Filter
  field, op: "eq" | "neq" | "in" | "isTrue" | "isFalse" | "gt" | "gte" | "lt" | "lte"
  value?: ...
```

**Configurable knobs (install settings / env — do not scatter magic numbers):**

| Knob | Suggested default | Purpose |
|---|---|---|
| `query_limit_default` | 50 | Used when `limit` omitted |
| `query_limit_max` | 500 | Compiler clamp for row/group lists |
| `query_group_by_max` | 2 | Max `groupBy` fields |
| `time_range_max_days` | 366 | Cap for absolute `{ from, to }` |
| `spec_sections_max` | 12 | Spec validator |
| `spec_components_per_section_max` | 8 | Spec validator |
| `job_plan_result_ttl_hours` | 24 | `jobs.expires_at` for plan results |
| `job_poll_interval_ms` / backoff cap | 2000 / 10000 | UI suggestion only — not API law |

Rules for knobs:

- Read in one place (settings/env → small config object). Query engine, spec
  validator, time_window, and jobs TTL **must not** re-hardcode these.
- Suggested defaults above are **starting values**, not product forever-laws.
- Missing `limit` → `query_limit_default`. Requested limit → clamp to
  `query_limit_max` (optional warning in ExecuteResult metrics).
- Aggregates: `limit` applies to number of **groups** returned (document that).
- Exports/CSV (later) may use a separate higher ceiling.
- Window **preset names** shipped initially:
  `execution_date` | `last_7_days` | `last_14_days` | `study_to_date`.
  Adding `last_30_days` (etc.) is a **catalog/config extension**, not a new
  engine — do not treat the four presets as the only ranges users will ever need
  (absolute `{ from, to }` already covers arbitrary ranges).

**Intentional product / safety rules (not knobs — keep):**

- Spec `Query.window` = presets only (no ISO in saved templates).
- Execute/UI may pass absolute `{ from, to }`.
- LLM must not invent rate formulas; rates are catalog/compiler-defined.
- Study scope: always `study_id = :studyId` on denormalized columns.
- No certified tools / seed templates / `ReportRun` / `generated_content` truth.
- Planner: at most **one** repair LLM call, then fail (cost/latency policy).
- `is_clean` ⇔ zero DQA flags; severity red-wins (domain).
- Skip Kobo meta / `start`/`end` in answers (archive stays on `submissions.data`).
- In-process jobs for now (no Celery/Redis) — ops choice, revisit later.

**Hidden assumptions to avoid (called out so Auto does not invent them):**

- Default timezone is **`Study.timezone`**, not a global “always Asia/Kolkata.”
  Asia/Kolkata appears in fixtures and as Study model default only.
- Filter ops include comparisons (`gt`/`gte`/`lt`/`lte`) for numeric/date-like
  dimensions — do not ship eq-only and block “duration > 60” style asks.
- Chart kinds: initial set is `bar` | `bar_horizontal` | `stacked_bar` | `line` |
  `area` | `pie` | `donut` (§3.4). Adding a kind is display/renderer work, not a
  new query engine.
- “Median duration / ranking / stacked bar not rebuilt” in Phase 5 means
  **not required for cutover**, not “forbidden forever.”
- Absolute execute `{ from, to }` overriding all component presets for that run
  is intentional UX for a single date-picker; document in API.

**Window presets vs absolute ranges (required clarity):**

| Layer | What it stores | May contain ISO dates? |
|---|---|---|
| `Query.window` in saved **ReportSpec** | Preset only (`execution_date`, `last_7_days`, …) | **No** — templates stay reusable |
| **Execute job** / UI list filters | Preset **or** absolute `{ from, to }` | **Yes** — run-time / screen filter |
| **ExecuteResult.window** | Resolved `{ from, to }` | Yes — what actually ran |

**Shared time-window contract** (reports **and** dashboard / DQA / submissions):

Product needs date-range filtering in many places, not only reports. Implement
**one** resolver used by Query IR, report execute, and other study-scoped UIs:

```text
# app/domain/time_window.py  (or app/services/time_windows.py — one module)

TimeWindowInput (API / job / query-string shape)
  # exactly one of:
  preset?: "execution_date" | "last_7_days" | "last_14_days" | "study_to_date"
  executionDate?: "YYYY-MM-DD"   # anchor day for presets; default = today in study TZ
  # OR absolute inclusive study-local calendar days:
  from?: "YYYY-MM-DD"
  to?: "YYYY-MM-DD"

ResolvedTimeWindow
  from_date: date              # study-local calendar day inclusive
  to_date: date
  utc_start: datetime          # inclusive bound for submitted_at
  utc_end: datetime            # exclusive or inclusive — pick one, document, test
  timezone: str
  source: "preset" | "range"
```

Rules:

- Resolve in **Python** with the study timezone. Do **not** use SQLite IANA TZ.
- Absolute `from`/`to` are **study-local calendar dates**, inclusive on both ends
  for “which days’ submissions,” then converted to UTC bounds for SQL.
- Reject `from > to`. Cap range length via `time_range_max_days` (configurable;
  suggested default 366) — not a frozen forever constant.
- Spec / Query IR validators still reject ISO dates inside `Query.window`.
- Report execute payload:
  ```text
  window: { preset, executionDate? } | { from, to }
  ```
  When the job supplies `{ from, to }`, **every** component query uses that
  resolved range (overrides the preset named in the spec for that run). When
  the job supplies a preset **or only `executionDate`**, each component’s
  `Query.window` preset is resolved against that anchor (default = today in
  **study timezone**).
- **Cross-cutting adoption (same helper):** dashboard dateFrom/dateTo, DQA list
  filters, submissions grid filters, and report execute/preview must call this
  module — do not invent a second date-math path. Migrating those UIs/APIs onto
  the shared helper is **in scope** of this rewrite (Phase 2 lands the module;
  wire report execute in Phase 3; retarget dashboard/DQA/submissions filters in
  Phase 5 or earlier when touching those routers — empty-state OK until then,
  but do not leave divergent date logic once you touch a screen).

Resolve presets against `executionDate` in **`Study.timezone`** (fallback only
if study missing: install default timezone from settings — do not assume
Asia/Kolkata in engine code). Absolute ranges and presets both become the same
`ResolvedTimeWindow` bind params.

**Entities and columns (catalog — this is what the LLM sees):**

`submission` (join `submissions` + `submission_quality` + `projects` + `study_tools`
for study/tool/target):

- dimensions: `enumerator`, `toolCode`, `projectId`, `day` (from `calendar_day`)
- facts: `isClean`, `maxSeverity`, `flagCount`, `redCount`, `amberCount`,
  `durationMinutes`, `targetCount` (from `StudyTool.target_count` via join —
  for progress/coverage; not a named `tool_coverage` tool)
- measures: count, countWhere on bools, countDistinct enumerator, avg/sum durationMinutes

`flag` (join `dqa_flags` + submission clock + project/study):

- dimensions: `enumerator`, `toolCode`, `projectId`, `severity`, `ruleId`,
  `ruleTitle`, `day`
- measures: count, countDistinct submissionId
- row list: enumerator, ruleTitle, toolCode, severity (bounded by limit).
  UDISE only if already denormalized somewhere — do not invent a UDISE tool.

`answer`:

- dimensions: `fieldKey`, `enumerator`, `toolCode`, `day`
- filters must include `fieldKey` eq when aggregating answers
- measures: count, countDistinct submissionId, avg/sum `valueNumber` only if type is number

**Rates / percents:** display format over two measures, or one derived measure with
a **fixed** definition in the compiler/catalog. LLM must not invent rate formulas.

Compiler: `app/services/reporting/query_engine.py`

- Allowlist every identifier (entity, column, op, fn). Unknown → `QueryError`.
- Always `AND study_id = :studyId` on the entity’s denormalized `study_id`
  column (`submissions.study_id`, `dqa_flags.study_id`, or projection
  `study_id`). Do not scope only via `JOIN projects` and hope — orphans and
  stale joins leak. Rows with `study_id IS NULL` never appear in a study query.
- Apply `ResolvedTimeWindow` UTC bounds to the reporting clock (`submitted_at`
  and/or `calendar_day` — pick one primary, document, test both preset and
  absolute range).
- SELECT only. Parameterized. No f-string interpolation of field names from LLM
  unless they passed the allowlist set lookup first.
- `limit` applied in SQL.
- `durationMinutes` / `day` read denormalized columns — never `json_extract` on
  `submissions.data` for production aggregates.
- Return `list[dict]` for grouped/row queries, `dict` for ungrouped measures.

### 3.4 ReportSpec

`app/domain/reporting/spec.py`

```text
ReportSpec
  specVersion: "1.0"
  title: str
  subtitle?: str
  sections: list[Section]     # max from spec_sections_max config

Section
  id, title, description?
  components: list[Component] # max from spec_components_per_section_max config

Component
  id
  type: metric | kpi_group | table | chart | progress | narrative | text
  query?: Query               # required except text; narrative may use { uses: [componentId] }
  display: type-specific
```

Display (initial set — keep small; extend renderer, not query engine):

- `metric`: `{ label, field, format? }`
- `kpi_group`: `{ items: [{ label, field, format? }] }`
- `table`: `{ columns: [field], sort?, emptyText? }`
- `chart`: see **Chart kinds** below
- `progress`: `{ labelField, valueField, targetField }` — `targetField` may be
  `targetCount` from the submission/tool join
- `narrative`: `{ role: insight|warning|action, instruction, maxWords? }`
- `text`: `{ body, style?: prose|note }` — static; no `{{placeholders}}`

**Chart kinds (initial — aim ~70–80% of field/DQA report asks):**

Same component type `chart`; `kind` selects the renderer. Data is still
`list[dict]` from Query IR — charts do not get a separate query language.

```text
chart.display:
  kind: bar | bar_horizontal | stacked_bar | line | area | pie | donut
  x: str                 # category / day field
  y: list[str]           # one or more measure fields (multi-series)
  seriesField?: str      # optional: pivot a long column into series (stacked/multi)
  stacked?: bool         # only for bar / bar_horizontal; stacked_bar implies true
  limit?: int            # optional display trim; still clamped by query_limit_*
```

| Kind | Covers | Typical Infosutra asks |
|---|---|---|
| `bar` | Category comparison | Submissions / flags by enumerator or tool |
| `bar_horizontal` | Rankings, long labels | Top failing rules, long enumerator names |
| `stacked_bar` | Part-to-whole by category | Clean vs flagged by enumerator; severity mix by tool |
| `line` | Trend over time | Flag rate or submission count by `day` |
| `area` | Trend + volume | Cumulative submissions / open issues over the window |
| `pie` / `donut` | Simple share (few slices) | Severity share; tool share of volume |

**Why this set:** bar + stacked + line already cover most analytics; horizontal
bar and area fill ranking/volume; pie/donut absorb “show me the split” asks.
Together they handle the large majority of study-ops report requests without
scatter/heatmap/waterfall complexity.

**Explicitly defer (not required for first ship):** scatter, heatmap, histogram,
boxplot, waterfall, funnel, treemap, radar, sankey, combo dual-axis. Add later
as renderer-only extensions when English repeatedly asks.

**Renderer rules:**

- Prefer Recharts (already in the UI) for preview; PDF maps the same kinds via
  ReportLab (or simplified static equivalents — document gaps).
- Cap pie/donut slices (e.g. top N + “Other”) using `limit` / config — avoid
  30-wedge pies.
- Multi-series: `y: [clean, flagged]` or `seriesField` + one `y` measure.
- Planner catalog lists these `kind` values; unknown kind → validation error /
  unmapped, not a silent drop.

Validator (`app/domain/reporting/validation.py`):

- JSON schema / Pydantic `extra=forbid`
- Every query field/entity legal in catalog
- `uses` ids exist
- no ISO dates in spec `Query.window`
- section/component counts from config knobs (§3.3)
- no SQL/script in text/instruction
- unmapped is **not** stored on the spec; it lives on PlanResult only

**Forbidden in spec:** `data_source`, certified tool ids, `report_kind` affecting queries.

### 3.5 Plan result / execute result

```text
PlanResult
  spec: ReportSpec
  unmapped: [{ userIntent, reason }]
  judgement: { faithful: bool, issues: string[] }

ExecuteResult
  reportId
  title
  window: { from, to }
  sections: [{ id, title, components: [{ id, type, data, error? }] }]
  artifacts: { pdf?: url }
```

`data` shapes:

- metric: number or `{ value }`
- kpi_group: `{ [field]: number }`
- table/chart/progress: `list[dict]`
- narrative: `{ text }`
- text: `{ body }` (from spec)

One failing query sets that component’s `error`; other components still fill.

**Canonical:** ExecuteResult JSON **file** (path on `Report` / job `result_ref`).
HTML (if kept for print/legacy viewer) and PDF are pure functions of that JSON —
never a second query pass, never a second source of truth. Persist the file;
do not keep a duplicate multi‑MB JSON column as truth.

### 3.6 Planner (phase 4)

Not LangGraph. Linear:

1. Build catalog JSON from entity schemas + this study’s answer `fieldKey`s
   (distinct keys from `submission_answers` for the study, with labels).
2. Load **system prompts from the `prompts` table** (see below) — not from a
   buried-only code string the UI cannot show.
3. One structured-output LLM call (reuse `app/integrations/llm`).
4. Validate. If invalid, **one** repair call with validator errors. Then fail the job.
5. Judge: second LLM call, original user text vs spec; produce `faithful` + issues.
   Unmapped / `faithful: false` does **not** fail the job.

Mock LLM in tests with returned JSON. No network.

Patch (compose): input includes `currentSpec`; patch system prompt says “patch,
do not drop unrelated sections.” Same `type: plan`.

**System prompts are product data (required):**

Reporting LLM instructions must be visible and editable in the UI via the
existing Prompts surface (`PromptTemplates` / `/prompts` APIs), not only in
git. This is **not** the same as seed *report templates* (layouts) — those stay
banned. AI system prompts are install configuration.

| Prompt role | Stable id (example) | Used by |
|---|---|---|
| Plan (English → ReportSpec) | e.g. `report-planner` | `type=plan` step 3 |
| Plan repair | e.g. `report-planner-repair` | step 4 (or same prompt + repair user msg) |
| Judge | e.g. `report-planner-judge` | step 5 |
| Narrative / analyst | e.g. `report-analyst` | execute narrative components |

Rules:

- Resolve at job runtime: `db` → `Prompt.content` by id/category. Prefer the
  existing seed-if-missing pattern (`seed_*_prompts` on boot) so a wipe still
  gets defaults; **defaults also live as editable rows** the UI lists.
- Code may keep a `DEFAULT_*` string **only** as the seed source for first
  insert / revert-to-default — the live path always reads the DB row.
- Prompt builder still injects dynamic catalog + ReportSpec schema JSON into the
  **user/message** (or a clearly separated appendix block). Do not bake the
  whole study catalog into the stored system prompt.
- System prompt text **must not** name legacy tool ids or Daily/Final recipes.
- UI: list/edit these prompts on the Prompts page now. **RBAC later:** restrict
  that page (or these categories) to admin — do not invent RBAC in this rewrite;
  structure ids/categories so admin gating is a filter later, not a redesign.
- Do not delete system prompt rows from the API (keep current protection).

---

## 4. Phases

Each phase: implement → tests listed → run gate commands → only then next phase.

### Phase 0 — Schema baseline + job platform

**Signed off:** wipe prototype data. Do not migrate old reports/seeds/`ReportRun`.

**Wipe (local):**

```bash
# Stop the API. Paths may vary — use the project’s configured SQLite + data dirs.
rm -f path/to/app.db   # or whatever DATABASE_URL points at
rm -rf data/reports data/jobs   # PDF/DOCX + job result files
# Then apply the new Alembic baseline / create_all from updated models.
```

**Schema (models + one fresh Alembic baseline — see §3.0):**

- Add `jobs` (`result_ref`; **no** result JSON/Text column)
- Add empty `submission_answers`, `submission_quality`
- Add `submissions.study_id`, `duration_minutes`, `calendar_day`
- Add `dqa_flags.study_id`
- Add `reports.result_ref`; **remove** `reports.generated_content` as truth
  (delete the column)
- **Remove** `report_runs` table + `ReportRun` model
- **Remove** `report_templates.is_system`
- `report_templates.study_id` NOT NULL; `report_schedules.template_id` NOT NULL
- **Remove** `AppSettings.daily_report_*` columns
- Drop or neutralize `Study.daily_report_template_id` /
  `final_report_template_id` seed fallbacks (prefer drop; else document as
  optional user assignment only, never `seed-dqa-*`)
- Fix soft FKs where cheap (`current_version_id` → real FK)

**Code that must change so the app boots (same phase — break reporting OK):**

- Delete `app/services/report_seed_templates.py` and lifespan seed call
- Delete `ReportRun` model/usages; delete `is_system` / `generated_content` /
  settings `daily_report_*` usages
- Stub or remove Generate / Preview / schedule paths that cannot run without
  legacy blobs or seeds — empty state + CTA is fine until Phase 3–5 restore them
  on jobs
- If `report_tools` / LangGraph / `execute_spec` / `dqa_*_report` break the
  import graph, **delete those modules and call sites now** rather than
  wrapping them. Do not keep dead packages “for Phase 5.”
- Keep Kobo sync + DQA eval importable and tested
- Rewrite/delete failing tests that assert seeds / ReportRun / generated_content

**Job platform files:**

- `app/db/models/jobs.py` + exports in `app/db/models/__init__.py`
- `app/services/jobs/artifacts.py` (or extend `report_storage.py`) —
  `write_job_result` / `read_job_result` / `delete_job_result` → e.g.
  `data/jobs/{job_id}.json`
- `app/services/jobs/store.py` enqueue/get/claim/complete/fail
  (SQLite claim: `UPDATE … WHERE status='pending'`;
  `complete` writes file then `result_ref`;
  `get_for_api` hydrates `result`)
- `app/services/jobs/worker.py` dispatch by type
- `app/routers/jobs.py` POST/GET — response exposes `result`, never `result_ref`
- Register router + worker tick in `app/main.py` (budget claims so Kobo/email
  ticks are not starved)

**Handlers:** `echo` (tests) or stubs writing `{"ok": true}` via artifacts.
Real plan/execute later.

**Tests:**

- `tests/test_reporting_schema_baseline.py` (or assert in models test):
  - no `ReportRun` / `report_runs`
  - no `is_system` on templates
  - no `generated_content` on reports; `result_ref` present
  - no `daily_report_*` on settings
  - `jobs`, `submission_answers`, `submission_quality` exist
  - `submissions` has `study_id`, `duration_minutes`, `calendar_day`
- `tests/test_jobs.py`
  - POST → 202, GET pending (`result` absent)
  - Worker completes echo → file on disk; DB has `result_ref` only; GET hydrates
    `result`; response has no `result_ref`
  - GET 404; fail → `error`, no result file
  - Concurrent two jobs complete; G2 sleep test
  - Optional: expire deletes result file

**Gate:**

```bash
uv run pytest tests/test_reporting_schema_baseline.py tests/test_jobs.py -q
# jobs model must not have a result JSON/Text column
# no ReportRun model importable from app.db.models
rg -n "seed_report_templates|class ReportRun|generated_content|is_system" \
  artifacts/api-python/app/db artifacts/api-python/app/main.py
# expect no matches for those symbols (except historical comments if any)
```

Do not migrate transcription onto jobs unless free. Reporting is the first client.

---

### Phase 1 — Ingest projection writers

Tables already exist from Phase 0. This phase **writes** facts on sync/eval.

**Files:**

- `app/services/reporting/answers.py` `replace_answers_for_submission(...)`
- `app/services/reporting/quality.py` `upsert_quality_for_submission(...)`
- Module docstring: `start`/`end` → duration column only, not answers; Kobo meta
  skip-list; reuse `form_labels` / `list_form_fields`
- Wire:
  - kobo_sync: after submission upsert flush → answers + `study_id` +
    `duration_minutes` + `calendar_day`
  - flag writes / eval: set `dqa_flags.study_id`
  - `evaluate_submission`: upsert quality (zero flags → clean)
  - `evaluate_project` (+ cascade): upsert quality for **all** evaluated ids
- Test-only helper to insert projected rows without full sync (fixture support)

**Tests:** `tests/test_reporting_ingest.py`

- Sync-like JSON with two questions → two answer rows, labels from form_definition
- Re-upsert replaces answers (no duplicates)
- `_id` / `_uuid` / `_notes` / `_attachments` not stored as answers
- `start`/`end` not stored as answers; `duration_minutes` populated when parsable
- `calendar_day` matches study TZ for a known `submitted_at`
- `submissions.study_id` / `dqa_flags.study_id` match project
- Zero flags → `is_clean=true`, max_severity null, flag_count 0
- One amber → not clean, max_severity amber
- Amber + red → max_severity red, counts correct
- Delete/re-eval flags updates quality
- Prune submission cascades answers + quality
- null study → no answer/quality projection rows
- Reassign project to another study (or unassign) → child `study_id`s rewritten
  or projections cleared; Query IR for old study no longer returns those rows

**Gate:**

```bash
uv run pytest tests/test_reporting_ingest.py tests/test_kobo_sync*.py tests/test_dqa*.py -q
```

Existing Kobo/DQA tests must still pass. Dual-write only (raw `data` still stored).

---

### Phase 2 — Query engine (no HTTP, no LLM)

**Files:**

- `app/domain/time_window.py` — shared `TimeWindowInput` / `ResolvedTimeWindow`
  resolver (study TZ). **Not** reporting-only; dashboard/DQA/submissions will
  import this. Copy useful semantics from `app/domain/reporting/date_windows.py`
  then stop using the old helper for new code.
- `app/domain/reporting/query.py`
- `app/domain/reporting/catalog.py` (entity/column allowlists including
  `targetCount`, `durationMinutes`, `day` → `calendar_day`)
- `app/services/reporting/query_engine.py` — takes `ResolvedTimeWindow` + study_id;
  reads limit / groupBy max knobs from settings (not hard-coded)
- Wire settings keys for the §3.3 knobs (`query_limit_*`, `query_group_by_max`,
  `time_range_max_days`, spec size caps) with suggested defaults — one module

**Tests:**

- `tests/test_time_window.py` — preset → bounds; `{ from, to }` → bounds;
  `from > to` rejected; range cap from config; study TZ edge (IST day ≠ UTC day);
  executionDate anchor for `last_7_days`
- `tests/test_reporting_query_engine.py` with a seeded study:
  include case that raising `query_limit_max` in test settings allows a higher
  clamp (proves knobs are not frozen in code)

Fixture (lock these numbers — they are the golden e2e):

- Study tz Asia/Kolkata, executionDate 2026-09-12
- Meena: 8 clean submissions that day
- Ravi: 12 submissions, 2 amber flags (skip pattern)
- Arun: 5 submissions, 3 red flags (GPS ×2, duration ×1)
- Totals: 25 submissions, 20 clean, 5 flagged
- Fixture writes `duration_minutes`, `calendar_day`, answers, quality — not only
  raw `Submission.data`

Cases:

1. Ungrouped count + countWhere isClean → `{total:25, clean:20, flagged:5}`
2. groupBy enumerator → three rows, Meena 8/8/0, Ravi 12/10/2, Arun 5/2/3
3. flag rows severity=red limit 50 → 3 rows, all Arun
4. last_7_days ≠ execution_date (seed an extra older row; it must appear only in 7d)
5. Absolute `{ from, to }` equal to execution day matches case 1; wider range
   includes the older row
6. Reject unknown entity, unknown column, unknown op, groupBy of 3 fields
7. Reject identifier that looks like SQL (`enumerator; DROP`)
8. `study_id` of another study → empty, never leakage; orphan project
   (`study_id IS NULL`) never appears in a study query
9. `limit` honored
10. Compiler does not call `build_daily_dqa_stats` / `entity_rows` / `call_tool`
11. Compiler does not `json_extract` / read `submissions.data` for aggregates
12. `groupBy: day` uses `calendar_day` column
13. Optional progress: measure/count vs `targetCount` join returns expected shape

Assert SQL uses bound params (inspect compiled statement or use a spy).

**Gate:**

```bash
uv run pytest tests/test_time_window.py tests/test_reporting_query_engine.py -q
```

**Do not** implement renderers yet.

---

### Phase 3 — ReportSpec, execute job, result file + PDF, preview UI

**Files:**

- `app/domain/reporting/spec.py` + `validation.py`
- `app/services/reporting/execute.py` — load spec, run queries, assemble ExecuteResult
- `app/services/reporting/render_pdf.py` — PDF from ExecuteResult only (ReportLab OK).
  Do not re-query.
- Optional `render_html.py` — pure function of ExecuteResult for legacy iframe
- Job handler `type=execute` payload:
  ```text
  { templateId? | spec,
    window: { preset, executionDate? } | { from, to } }
  ```
  Resolve via shared `time_window` module; put resolved `{ from, to }` on
  ExecuteResult. Absolute range overrides component presets for that run.
- Persist `Report` row with `spec_json` + **`result_ref`** to ExecuteResult file
  (canonical). Preview/download hydrate from the file the same way
  `GET /jobs/{id}` does. HTML may be derived at serve time. PDF file remains
  separate on disk. Do **not** reintroduce `generated_content`.
- Complete the execute job by writing ExecuteResult via job artifacts
  (`result_ref`); `GET /jobs/{id}` returns the hydrated JSON in one response.
- Do **not** revive seed Daily/Final generate (removed in Phase 0).

**Tests:**

- `tests/test_reporting_spec_validation.py` — extra fields forbidden; bad entity;
  ISO date in **spec Query.window** rejected; text `{{foo}}` rejected
- `tests/test_reporting_execute.py` — golden spec (section 5 below) against
  phase-2 fixture → ExecuteResult numbers match; one bad query → that component
  errors, KPIs still present; PDF from ExecuteResult without re-query;
  execute with `{ from, to }` matching fixture day → same counts
- `tests/test_reporting_execute_job.py` — POST execute 202; worker completes;
  result file on disk; DB has `result_ref` not inline blob; GET hydrates
  datasets in `result`; PDF bytes non-empty; no `ReportRun` row created for
  this job
- Router does not import `execute_spec` from v1

**Frontend (minimal for this phase):**

- New or parallel preview path that polls `GET /jobs/{id}` (suggested ~2s with
  backoff; UI-only, not an API contract), `jobId` in URL query, renders
  **`result` from that single response** (ExecuteResult JSON). No second fetch
  for the artifact file.
- Do not center on unused `SpecPreview.tsx` unless you wire it as that JSON
  renderer. Do **not** keep a legacy HTML preview that reads `generated_content`
  (column removed in Phase 0). Preview = execute job → hydrated ExecuteResult.
- Do not build section-card review yet.

**Gate:**

```bash
uv run pytest tests/test_reporting_spec_validation.py tests/test_reporting_execute.py tests/test_reporting_execute_job.py -q
pnpm run api:client && pnpm run typecheck
```

G2: `artifacts/api-python/app/routers/` must not call `query_engine.run` or
`chat_completion` directly (grep).

---

### Phase 4 — Plan job, section cards, compose + create template

**Files:**

- `app/services/reporting/catalog_for_llm.py`
- `app/services/reporting/planner.py` — linear plan/repair/judge; loads prompts
  from DB
- `app/services/reporting/prompt_seeds.py` (or extend existing seed helpers) —
  DEFAULT text + seed-if-missing for planner / repair / judge / analyst ids;
  **not** a runtime-only `prompts.py` that hides copy from the UI
- Keep / reuse `prompts` CRUD + `PromptTemplates` UI; ensure new reporting prompt
  ids appear there after seed
- Job handler `type=plan`
- **Authoring uses ReportSpec only** (delete legacy planner paths):
  - `POST /jobs` type=plan + template save with `specVersion=1.0`
  - Delete SSE `/create/stream`, LangGraph planner call sites, and legacy
    `plan_spec` paths when wiring this phase — do not leave them “for later”
  - Template versions store `spec_version` `"1.0"` for new rows
- Conversations: each turn enqueues `plan` with `currentSpec`; poll; store
  snapshot. Delete old inline conversation planner if it still exists.

**Tests:** `tests/test_reporting_planner.py`

- Mock LLM returns golden spec → PlanResult spec validates
- Mock LLM returns Slack delivery section → unmapped, spec has no Slack component
- Mock invalid JSON → one repair; still invalid → job failed
- Mock spec with `data_source: study_totals` → validator fail
- Patch: current spec has 3 sections; LLM patch adds a chart; unrelated sections remain
- POST plan 202; GET completed includes unmapped + judgement; no `ReportRun` row
- Seeded planner/judge/analyst prompt rows exist and `GET /prompts` returns them
- Editing prompt content in DB is what the planner loads (not a stale code-only string)
- Prompt content **must not** contain strings:
  `enumerator_performance`, `study_totals`, `signoff_checklist`, `query_aggregate`
- Smoke: app boots; template CRUD for `spec_version=1.0` works without report-template seeds
- Grep: no `plan_spec(` / LangGraph report planner under `app/`

**Frontend:**

- Create template: textarea → POST plan job → poll → **section cards**
  (title, type, one-line summary of query, unmapped banner) → Save
- Compose: same cards after each turn; Save as template
- Optional: Preview button starts execute job (phase 3)
- Prompts page: reporting system prompts visible/editable (admin-only later via RBAC)
- No SSE dependency

**Gate:**

```bash
uv run pytest tests/test_reporting_planner.py tests/test_reporting_execute_job.py -q
rg -n "enumerator_performance|study_totals|signoff_checklist|query_aggregate" \
  artifacts/api-python/app/services/reporting artifacts/api-python/app/domain/reporting
# must be empty
rg -n "report_planner|plan_spec\(|/create/stream" artifacts/api-python/app
# expect no matches
```

---

### Phase 5 — Final product sweep (residual deletes + UI)

**Most legacy reporting should already be gone** by Phases 0–4 under break-and-fix.
This phase is the **final grep + UI cutover**, not the first deletion pass.

**Product rule (signed off): no default / system report templates.**

- Confirm seeds / `is_system` / `seed-dqa-*` are fully gone.
- Users must **author and save** a template before Generate or schedule can run.
- `/reports`: template picker (or study-assigned template id). If none → empty
  state + link to Create template / Compose.
- Schedules require `template_id`; enqueue execute then email.
- “Daily” / “Final” may remain as **labels** on a user template or schedule
  (window presets), not as engine kinds.

**Catalog capabilities (must support if English asks — not a shipped Daily pack):**

- Submission / clean / flagged counts (one window per query; two components if
  today + cumulative are both needed)
- Enumerator breakdown with clean/flagged
- Red flag row list (bounded; ruleTitle, enumerator, toolCode)
- Progress vs `StudyTool.target_count` via join/`targetCount`
- Optional: `groupBy day` flag rate if `calendar_day` exists

**Explicitly not rebuilt as tools or required defaults (approved):**

- Assembled `signoff_checklist` / `compose_signoff_checklist`
- `triangulation_summary` as a report tool
- Dual-window mega-objects like `study_totals`
- Median / ranking / stacked-bar as **required cutover** features (may add later
  as catalog/renderer extensions — not blocked forever)
- Any Python `build_*_dqa_spec` / boot-time seed refresh

**Hard gate:** golden execute + planner tests pass; Generate / schedule refuse
without a user-saved `templateId`; final greps below are clean.

**Date-range UI (shared `time_window`):** retarget dashboard `dateFrom`/`dateTo`,
DQA list filters, and submissions grid filters to the same
`TimeWindowInput` → `ResolvedTimeWindow` helper. No bespoke date math left in
those routers/services once touched. Report execute already uses it from Phase 3.

**Entrypoints (all use the new reporting stack):**

| Entrypoint | After cutover |
|---|---|
| `/reports` Generate | Template picker → enqueue `execute`; disabled if none |
| Template / Composer Preview | Enqueue `execute`, poll, render ExecuteResult |
| Create template / Compose | Jobs `type=plan` + section cards |
| `ReportSchedule` / send-now | Enqueue `execute` then `email` with PDF + recipients |
| Legacy digest `daily_report` | Deleted |

**Delete anything still left (grep must go quiet in `app/`):**

- `app/services/report_tools/` (sources, query_aggregate, signoff, …)
- `dqa_daily_report.py`, `dqa_final_report.py`, `daily_report.py`
- Any remaining seed / LangGraph / `execute_spec` / legacy report_spec engine
- Any revived `ReportRun` / `is_system` / `generated_content` usage

Keep DQA **evaluation** (flags). Keep studies, Kobo sync, template/conversation
tables. Keep triangulation as a **DQA UI** feature if needed — not a report tool.

**Rewrite/replace** any remaining legacy tool/seed tests. Do not keep
`tests/test_report_tools.py` green by leaving sources.py.

**Final gate (all must pass):**

```bash
cd artifacts/api-python && uv run pytest -q
# from repo root:
pnpm run api:client && pnpm run typecheck

# legacy catalog must be gone from app code:
rg -n "enumerator_performance_today|signoff_checklist|triangulation_summary|call_tool\(|seed_report_templates|seed-dqa-daily|seed-dqa-final" \
  artifacts/api-python/app
# expect no matches (docs/tests mentioning history OK)

# G2
rg -n "plan_spec\(|execute_spec\(|chat_completion|query_engine" \
  artifacts/api-python/app/routers
# routers may import job enqueue only — not those symbols

# G1
rg -n "def enumerator_|def study_totals|def top_failing" artifacts/api-python/app
# expect no matches
```

Existing unrelated tests (Kobo, DQA rules, dashboard) must still pass.

---
## 5. Golden set (tests only — not product defaults)

The golden set is a **test fixture**, not a shipped Daily report. It proves the
engine. Put the spec in `tests/fixtures/reporting_golden_spec.json` and the
DB rows in the Phase 2 test fixture.

### Keep (still the right e2e)

User intent (planner tests):

> Today’s submissions by enumerator, clean vs flagged. List the red flagged
> interviews with enumerator and rule. Write a short note on what looks
> concerning. Also push it to Slack.

Expected PlanResult:

- `s1c1` kpi_group — submission counts (total / clean / flagged), `execution_date`
- `s2c1` table — groupBy enumerator
- `s3c1` table — flag rows, severity=red
- `s3c2` narrative — uses those three, role warning
- `unmapped`: Slack delivery (no delivery primitive in the report engine)

Execute on the fixture (Meena 8 clean, Ravi 12 with 2 amber, Arun 5 with 3 red):

- total 25, clean 20, flagged 5
- 3 enumerator rows; 3 red rows all Arun P.
- narrative mock fixed string in execute tests

This still matches the product: English → spec → SQL → result. Slack unmapped
still teaches the judge path.

### Drop / do not treat as golden (obsolete under no-seed decision)

These were leftovers from “must reproduce the old Daily pack”:

- Boot-time / system `seed-dqa-daily-template` / `seed-dqa-final-template` as a
  required artifact
- Sign-off checklist, triangulation table, dual-window `study_totals` mega-KPI,
  median duration, ranking/stacked-bar types as required golden sections
- “Hard gate = ship a reduced Daily seed before deleting sources”
- Definition of done that says Generate Daily on a **system** template

Coverage vs `targetCount` stays a **catalog** capability (user can ask for it in
English) — it is not a required section of the golden spec.

### How product reports appear after cutover

Someone authors the golden English (or any English) in Create template / Compose,
saves, then Generate or schedule uses **that** template. There is no second
“official” Daily JSON in the repo that the engine prefers.
---

## 6. Frontend checklist

| Screen | Behavior |
|---|---|
| `/report-templates` create | Plan job + section cards + save. Preview = execute job → ExecuteResult |
| `/report-composer` | Each send = plan job with currentSpec; cards; save as template |
| `/reports` (after Phase 0+) | Pick user template → execute job; empty state if none. Seed Generate removed with schema baseline. |
| Schedule | Requires template_id; execute then email jobs |
| Job id | `?job=` in URL; resume poll on refresh |
| Failed job | Show `error`, Retry enqueues a new job |
| Unmapped | Amber warning on cards, never silent drop |
| Canonical data | ExecuteResult JSON file; GET jobs hydrates it; HTML/PDF derived, not a second truth |
| Date filters | Reports + dashboard + DQA + submissions use shared `time_window` (`from`/`to` or preset) |
| System prompts | Planner / judge / analyst prompts listed & editable on Prompts UI (RBAC → admin later) |

Until Phase 5 greps are clean, reporting UI may be empty-state until surfaces are restored.
Do not keep SSE/HTML legacy demos. All authoring/preview/generate use jobs+poll.

---

## 7. Performance requirements (test what you can)

- Query engine tests: fixture of 200+ submissions; grouped query must not call
  `build_submission_entity_rows` / `aggregate()` / `json_extract` on `data`.
- `EXPLAIN` not required, but queries must be single SQL statements with
  `WHERE study_id` (or join) and `LIMIT`.
- Execute job runs component queries sequentially or in parallel; **no** full-study
  stats collapse (`build_daily_dqa_stats`).

---

## 8. Out of scope (do not do)

- Redis, Celery, Postgres migration (SQLite prototype OK; schema must still be
  portable)
- Rebuilding tenants/forms ERD from the prototype architecture plan
- Five prototype “section handlers” (MetricHandler, …) — query + render split instead
- Prototype `DynamicQueryBuilder` on raw `submissions.data` at report time
- New certified tools, sign-off assembler, triangulation **report** tool
- Inventing RBAC beyond existing study scoping
- Migrating all transcription/kobo to jobs in phase 0 (optional later)
- Keeping dual legacy/new reporting paths or “temporary” compatibility shims
- Shipping or boot-seeding system Daily/Final report templates
- One-click Generate that invents a layout the user never saved
- Data-migration scripts for wiped prototype rows
- Deleting `submissions.data` while DQA still needs the raw payload
- Breaking Kobo sync or DQA **evaluation** to rush reporting deletes
  (reporting may break; flag evaluation must not)

---

## 9. Suggested implementation order inside a session

If you cannot finish all phases, **stop at a completed gate**, commit that phase,
and update the `PHASE_STATUS` note at the top of this file.

Phase 0 is the largest early step (wipe + schema + jobs + delete broken v1
imports). Reporting may be down afterward — that is expected.

Never restore dropped columns to make old tests pass. Rewrite the tests.

---

## 10. Definition of done

A reviewer can:

1. Type the golden English on Create template, see section cards + Slack unmapped,
   save, preview, see 25/20/5 and Arun’s red rows (against the fixture or a seeded local DB).
2. Confirm `POST /jobs` returns 202 before completion.
3. Run the final gate greps in phase 5 with no forbidden matches under `app/`.
4. Add a new form question to a Kobo payload, re-sync, and filter/group that
   `fieldKey` via Query IR **without** a new Python handler.
5. Author a template, run it from `/reports` via execute job, and confirm a
   schedule can execute then email that same template — with no `sources.py`,
   no `seed_report_templates`, and no sign-off/triangulation report tools.
6. Confirm Generate / schedule are blocked with a clear CTA when the study has
   no saved template.
7. Confirm completed execute jobs store JSON on disk (`result_ref` only in DB)
   and `GET /jobs/{id}` returns hydrated `result` in one response (no client
   second fetch for the file).
8. Confirm Phase 0 schema baseline: no `report_runs`, no `is_system`, no
   `generated_content`, no settings `daily_report_*`; `jobs` + answers/quality
   tables present; wipe + re-sync is the supported reset path.
9. Confirm date filtering: report execute accepts `{ from, to }`; dashboard /
   DQA / submissions filters share `time_window` (no divergent date math).
10. Confirm reporting system prompts appear on the Prompts UI and are what the
    plan/execute jobs load (not code-only strings hidden from operators).

If any of those fail, the job is not done.

---

## 11. Amendment merge log

Grok-approved amendments A1–A10 were merged into §§0–10 on 2026-09-12:

| Amendment | Merged into |
|---|---|
| A1 denormalize duration/day | §3.2, Phase 1, Phase 2 |
| A2 hook points by name | §3.2, Phase 1 |
| A3 study scope / orphans / toolCode | §3.2, §3.3, Phase 1–2 tests |
| A4 Phase 4 coexistence | Superseded by break-and-fix (§2, Phase 4) |
| A5 ExecuteResult canonical / SpecPreview | §1, §3.5, Phase 3, §6 |
| A6 jobs replace ReportRun | §0 rule 9, §3.0–3.1, Phase 0 |
| A7 entrypoints map | Phase 5 |
| A8 drop-keep (no tools) | Phase 5 catalog capabilities |
| A9 targetCount / rates / flag fields | §3.3, Phase 2, Phase 5 |
| A10 confirmation checklist | Satisfied by merge |
| Product: no system seeds (option B) | §0 rule 10, §1, §2, Phase 0/5, §5, §6, §8, §10 |
| Product: schedule = generate then email | Phase 5 entrypoints, jobs `type=email` |
| Golden set trimmed | §5 — test fixture only; Daily seed hard gate removed |
| Job results on disk + GET hydrates | §0 rule 9, §3.1, §3.5, Phase 0/3, §6, §10 |
| Schema baseline wipe (prototype OK) | §0 rules 6/9/11, §2, §3.0–3.2, Phase 0/1/5, §8, §10 |
| Study_id denorm + reassignment | §3.2, §3.3, Phase 1 tests |
| Break-and-fix / no baggage | §0 rules 6/8/12, §2, Phase 0/4/5, §6, §8, §9 |
| Absolute date range + shared time_window | §3.3, Phase 2/3/5, §6, §10 |
| Configurable query limit default/max | §3.3 knobs, Phase 2 |
| Audit: other magic numbers → knobs / called-out assumptions | §3.3 knobs + intentional rules |
| No V1/V2 in code names (`ReportSpec`, `reporting/`) | §0 rule 13, §§3.3–3.6, Phases 0–5 |
| Initial rich chart kinds (bar/line/area/pie/…) | §3.4 |
| System prompts in DB + Prompts UI (admin RBAC later) | §0 rule 10, §3.6, Phase 4, §6, §10 |

No separate amendment block remains; this document is the single source of truth.
