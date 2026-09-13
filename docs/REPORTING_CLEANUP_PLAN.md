# Reporting cleanup — gap-closing plan (for Cursor Auto)

Parent spec: [`REPORTING_V2_IMPLEMENTATION_PLAN.md`](./REPORTING_V2_IMPLEMENTATION_PLAN.md).
Phases 0–5 of that rewrite are **done**. This document is **only** leftover
deletion and small contract fixes. Do **not** reopen the rewrite. Do **not**
add features.

Repo: `Data-Insights-Hub/`
API: `artifacts/api-python/`
UI: `artifacts/infosutra/`

```
<!-- CLEANUP_STATUS: all cleanup done -->
```

After each completed gate, update `CLEANUP_STATUS` to the next id
(`C0 done; next is C1`, …, `all cleanup done`).

---

## 0. Why this exists

A post–Phase 5 review found the **live path is on-spec**:

English → `plan` job → section cards → save template → `execute` job →
`result_ref` file + hydrated `GET /jobs/{id}`. Generate / schedule require a
user-saved `templateId`. Shared `time_window`. No `sources.py`, no seed report
templates, no `ReportRun`. Phase 5 greps are clean.

What is **not** on-spec is leftover intern bag/stats code still sitting under
`app/domain/reporting/`, a `ReportSpecV1` alias, inline SMTP on share, and UI
copy / study fields that still describe Daily/Final **report generators** that
no longer exist.

This cleanup makes the tree match the parent plan’s rule 8: prefer deleting
dead reporting code.

---

## 1. Operating rules

1. **Delete unused reporting bags.** Do not wrap them. Do not keep
   `compute_daily_dqa_stats` “in case.”
2. **Do not break** Kobo sync, DQA **evaluation** (flags), studies, jobs, Query
   IR, planner, execute, PDF, or template/compose UI.
3. **HTTP stays thin.** Routers enqueue jobs or do cheap CRUD. Do not call the
   LLM, query compiler, or PDF renderer in a router. Share-email must enqueue
   `type=email` (or execute+email), not SMTP in the request.
4. **No V1/V2 in identifiers.** Use `ReportSpec`. Never `ReportSpecV1` /
   `ReportSpecV2`.
5. **No new report tools, seeds, or `ReportRun`.** Forbidden greps from the
   parent Phase 5 gate must stay empty.
6. **Wipe-friendly is still OK.** A new Alembic revision to drop unused study
   prompt FKs is allowed. Do not write data-migration of old report blobs.
7. **Stop at phase gates.** Do not start C(n+1) until C(n) commands pass.
8. After public API change: from repo root `pnpm run api:client && pnpm run typecheck`.
9. Tests: `cd artifacts/api-python && uv run pytest -q`. Rewrite or delete tests
   that imported deleted modules. Do not restore deleted files to keep a test green.
10. **Do not commit** unless the user asks.

---

## 2. Keep vs delete

### Keep (live rewrite)

| Path / concept | Why |
|---|---|
| `app/domain/reporting/spec.py` `query.py` `catalog.py` `validation.py` | ReportSpec + Query IR |
| `app/domain/reporting/helpers.py` | Duration / calendar helpers used by **ingest** (`answers.py`) and schedule TZ. Trim only if a symbol becomes unused after deletes. |
| `app/services/reporting/*` | answers, quality, projections, query_engine, execute, planner, PDF, prompt_seeds, schedule_email |
| `app/services/jobs/*` | enqueue / claim / artifacts / worker (`plan`, `execute`, `email`) |
| `app/domain/time_window.py` | Shared date filters |
| `app/services/report_storage.py` | PDF/DOCX paths |
| `app/services/report_templates.py`, conversations, routers | Authoring + CRUD |
| `app/rendering/*` if execute/PDF still uses it | Derived HTML/PDF from ExecuteResult — keep if imported |
| Seeded prompts `report-planner`, `report-planner-repair`, `report-planner-judge`, `report-analyst`, DQA **compile** prompt | Config, not report layouts |
| `report_schedules.template_id` + `report_type` as a **label** | `daily_dqa` on a schedule is a window/label, not an engine kind. Do **not** restore Daily pack generation. |
| Validator reject-list of legacy tool ids in `validation.py` | Keep the strings (split if needed so parent greps stay quiet) |

### Delete (confirmed unused as of 2026-09-13)

No production importer outside the bag cluster itself. Safe to delete in C0:

| Path | Notes |
|---|---|
| `app/domain/reporting/entity_rows.py` | In-memory bags |
| `app/domain/reporting/aggregate.py` | In-memory bags |
| `app/domain/reporting/daily_stats.py` | `compute_daily_dqa_stats` |
| `app/domain/reporting/daily_enumerators.py` | |
| `app/domain/reporting/daily_trends.py` | |
| `app/domain/reporting/final_stats.py` | `enrich_final_checklist`, `_tr1_summary` |
| `app/domain/reporting/narratives.py` | Old Daily/Final prose fallbacks |
| `app/domain/reporting/domain_rules.py` | Only used by `daily_enumerators` |
| `app/domain/reporting/date_windows.py` | Bag window tokens |
| `app/domain/reporting/bag_query_catalog.py` | Intern catalog leftover |
| `app/repositories/reporting.py` | `load_study_report_inputs` — **zero callers** |
| `tests/fixtures/sample_daily_stats.json` | Orphan fixture |
| `tests/fixtures/sample_final_stats.json` | Orphan fixture |
| `docs/PHASE3_STATS_SHRINK_DESIGN.md` | Obsolete intern-stats design |

After deletes, rewrite `app/domain/reporting/__init__.py` to a **thin package**
(no Daily/Final re-exports). Either empty docstring + no `__all__` bag names, or
re-export only live symbols (`ReportSpec`, `Query`, `validate_report_spec`) if
something already imports them from the package root (today: nothing should).

### Do not delete

- `submissions.data` (DQA/UI archive)
- DQA evaluation, triangulation **as DQA UI**
- `helpers.duration_minutes` / `local_calendar_day` until ingest no longer needs them
- Job/result file storage
- User-authored `report_templates`

---

## 3. Known gaps (close these)

| Id | Gap | Required fix |
|---|---|---|
| G-dead | Dead bag/stats modules still in `app/` | C0 delete + greps |
| G-v1 | `from app.domain.reporting.spec import ReportSpec as ReportSpecV1` in `report_conversations.py` | Rename to `ReportSpec` |
| G-share | `POST /reports/{id}/share` calls `send_report_email` in the router | Enqueue `email` job; 202 + jobId (same shape as generate if possible) |
| G-copy | Settings “Daily consolidated report” help still describes the old digest | Rewrite to: scheduled execute of a **saved template**, then email |
| G-prompts-ui | Studies “Daily DQA / Final DQA” pickers write `daily_dqa_prompt_id` / `final_dqa_prompt_id` that **no execute/plan/insights path reads** | C2: remove orphan assignment UI + columns (or stop exposing them). Prompts page: stop presenting Daily/Final as shipped report voices |
| G-labels | Schedule routes still named `/schedules/daily-dqa` | Keep working; optional rename in C2. Label text may say “Scheduled report” |

Parent definition-of-done items 1 and 4 (browser golden English; new Kobo field
→ Query IR) are **product smoke**, not this cleanup. Do not block C0–C2 on them.

---

## 4. Phases

### C0 — Delete dead bag / Daily-Final stats code

**Do**

1. Delete the files listed in §2 Delete.
2. Slim `app/domain/reporting/__init__.py`.
3. Fix any accidental imports (there should be none). If `helpers.py` has
   symbols only bags used, delete those symbols only.
4. Keep `validation.py` legacy-id reject list.

**Do not**

- Touch query engine, planner, execute, ingest writers.
- Delete `helpers.py` wholesale.
- Change OpenAPI unless an unused export disappears (unlikely).

**Tests:** none new required. Existing `test_reporting_*` must still pass.

**Gate**

```bash
cd artifacts/api-python && uv run pytest tests/test_reporting_schema_baseline.py \
  tests/test_reporting_ingest.py tests/test_reporting_query_engine.py \
  tests/test_reporting_spec_validation.py tests/test_reporting_execute.py \
  tests/test_reporting_execute_job.py tests/test_reporting_planner.py tests/test_time_window.py -q

# dead modules gone
rg -n "compute_daily_dqa_stats|enrich_final_checklist|load_study_report_inputs|build_submission_entity_rows|bag_query_catalog" \
  artifacts/api-python/app
# expect no matches

# parent Phase 5 greps still clean
rg -n "enumerator_performance_today|signoff_checklist|triangulation_summary|call_tool\(|seed_report_templates|seed-dqa-daily|seed-dqa-final" \
  artifacts/api-python/app
rg -n "plan_spec\(|execute_spec\(|chat_completion|query_engine" artifacts/api-python/app/routers
rg -n "def enumerator_|def study_totals|def top_failing" artifacts/api-python/app
```

Then: `cd artifacts/api-python && uv run pytest -q` (full suite; Kobo/DQA must stay green).

---

### C1 — Naming + share-email is a job

**Do**

1. `report_conversations.py`: `ReportSpec` only. Grep `ReportSpecV1` → empty
   under `app/` and `artifacts/infosutra/src`.
2. `POST /reports/{id}/share`:
   - Require an existing generated report with a PDF (or `result_ref`) — same
     preconditions as today’s `send_report_email`.
   - Enqueue `type=email` with `{ reportId, recipients }` (reuse worker
     `_email_handler` / `send_report_email` **in the worker**, not the router).
   - Return **202** `{ jobId }` (add/reuse `JobCreated`). Do not SMTP in the
     request thread.
   - If the current `ShareResult` schema is still needed for the UI, either
     update the client to poll the job, or return 202 JobCreated and retarget
     the share button to poll like Generate. Prefer JobCreated — one async
     pattern.
3. Router must not import `send_report_email` after this change (worker and
   `schedule_email.py` may keep it).

**Gate**

```bash
rg -n "ReportSpecV1|reporting_v2|ReportSpecV2" artifacts/api-python/app artifacts/infosutra/src
# expect no matches

rg -n "send_report_email" artifacts/api-python/app/routers
# expect no matches

cd artifacts/api-python && uv run pytest -q
# from repo root, if OpenAPI changed:
pnpm run api:client && pnpm run typecheck
```

Add or extend a test: share returns 202; job type `email`; patched SMTP is
**not** invoked before the worker runs.

---

### C2 — Orphan Daily/Final report-prompt UX

The rewrite removed Daily/Final **report generators**. Study fields
`daily_dqa_prompt_id` / `final_dqa_prompt_id` are CRUD-only — nothing in plan,
execute, or insights reads them. That is leftover product, not DQA evaluation.

**Do**

1. **UI**
   - Remove the “DQA report prompts” Daily/Final pickers from
     `artifacts/infosutra/src/pages/studies/Studies.tsx`.
   - Prompts page (`PromptTemplates.tsx`): drop category chips/copy that imply
     shipped Daily/Final report voices. Keep categories users already created.
     Surface reporting system prompt categories (`report-planner`,
     `report-analyst`) so operators can edit what the planner loads.
   - Settings email help: replace “Daily consolidated report / Asia/Kolkata
     digest” with: schedules require a saved template; job = execute then email;
     timezone is **the study timezone**.
2. **API / schema**
   - Stop accepting/returning `dailyDqaPromptId` / `finalDqaPromptId` on study
     create/update/out (or leave them ignored — prefer drop).
   - Alembic: drop `studies.daily_dqa_prompt_id` and
     `studies.final_dqa_prompt_id` + FKs/indexes.
   - `prompts` router: stop treating those columns as prompt-in-use references.
3. **Schedules**
   - Keep `POST/PATCH …/schedules/daily-dqa` working (label). Optional: add
     display copy “Scheduled report (template + window)” in Studies schedule UI.
   - Do **not** invent a new seed template.

**Do not**

- Delete the DQA compile system prompt.
- Delete triangulation DQA UI.
- Reintroduce `seed-dqa-daily` / `seed-dqa-final` prompt ids.

**Gate**

```bash
rg -n "dailyDqaPromptId|finalDqaPromptId|daily_dqa_prompt_id|final_dqa_prompt_id" \
  artifacts/api-python/app artifacts/infosutra/src
# expect no matches (alembic history of old revisions OK)

rg -n "Daily consolidated report|shared Daily DQA|shared Final DQA" artifacts/infosutra/src
# expect no matches

cd artifacts/api-python && uv run pytest -q
# from repo root:
pnpm run api:client && pnpm run typecheck
```

---

### C3 — Final sweep (same bar as parent Phase 5 + this cleanup)

```bash
cd artifacts/api-python && uv run pytest -q

# from repo root
pnpm run api:client && pnpm run typecheck

# parent forbidden
rg -n "enumerator_performance_today|signoff_checklist|triangulation_summary|call_tool\(|seed_report_templates|seed-dqa-daily|seed-dqa-final" \
  artifacts/api-python/app

rg -n "plan_spec\(|execute_spec\(|chat_completion|query_engine" \
  artifacts/api-python/app/routers

rg -n "def enumerator_|def study_totals|def top_failing" artifacts/api-python/app

# this cleanup
rg -n "compute_daily_dqa_stats|enrich_final_checklist|load_study_report_inputs|build_submission_entity_rows|bag_query_catalog|ReportSpecV1" \
  artifacts/api-python/app

rg -n "send_report_email" artifacts/api-python/app/routers
```

All of the above: **no matches** in the listed trees (docs/tests mentioning
history are OK except `app/`).

Update `CLEANUP_STATUS` to `all cleanup done`.

---

## 5. Out of scope

- Celery, Redis, Postgres migration
- Real narrative-LLM polish beyond what Phase 3 already stubs
- New chart kinds, median/ranking as required work
- Browser golden-English DoD (parent §10 item 1) — optional follow-up
- Rebuilding Daily/Final as product defaults
- Deleting `submissions.data`
- RBAC beyond existing study scoping
- Renaming the whole `REPORTING_V2_IMPLEMENTATION_PLAN.md` filename

---

## 6. Definition of done

A reviewer can:

1. Confirm the §2 Delete files are gone and `domain/reporting/__init__.py` does
   not export Daily/Final stats.
2. Run C3 greps with no forbidden matches under `app/`.
3. Run full `uv run pytest -q` green; `pnpm run api:client && pnpm run typecheck`
   if the API changed.
4. Confirm share enqueues an email job (202) and routers do not call SMTP.
5. Confirm Studies no longer assigns unused Daily/Final report prompts; Settings
   help does not describe a built-in daily digest.
6. Confirm Generate / Compose / schedule still require a user-saved template.

If any of those fail, cleanup is not done.
