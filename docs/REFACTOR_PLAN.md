# Infosutra Refactor — Execution Plan ✅ COMPLETE

**Status:** All phases (0–7) completed 2026-08-11. Commits on `main`:
`abd1de8` → `d9e9621` (Phase 1), `db0da82` (2), `f860a63` (3), `7473697` (4),
`ad90e17` (5), `2dc899e` (6), `ec92ed5` (7). Tag: `pre-refactor-baseline`.

Specification for moving the codebase from its iteratively-grown state to a
loosely-coupled, multi-study architecture. Written to be executed **one phase per
session** by an agent.

**Decisions already made. Do not revisit them.**

- Existing local SQLite data may be dropped. No data migration is required.
- Tool codes are **study-defined labels**. `T1`/`T2`/`T3` is one study's naming
  convention, not a system concept.
- Study scoping in the UI is a **global study workspace**, not per-tab filters.
- Secret encryption stays **install-wide** (one env-derived Fernet key). Per-study
  credentials are separate *rows*, not separate *keys*.
- **One Kobo account per study.** A Kobo account is never shared across studies,
  so credentials belong to the study directly (`StudyCredential` with a
  `study_id` FK). Do not build a shared/reusable credential entity.
- **The four stub pages get wired to real data** in Phase 6, not hidden. See
  Phase 6 for the per-page scope, which is uneven.

---

## How to execute this plan

Each phase below has a **Preconditions** block, numbered **Tasks**, a
**Verification** block with commands and expected output, and **Stop and ask**
conditions.

Rules that apply to every phase:

1. Run the Preconditions check first. If it fails, stop — do not "fix it along
   the way."
2. Do not start a phase until the previous phase's Verification passes.
3. Verification means **running the command and reading the output**. Do not
   report success from reasoning about the code. Paste real output.
4. One phase, one commit. Do not bundle phases.
5. If you hit a **Stop and ask** condition, stop and report. Do not guess. These
   mark genuine product decisions, not obstacles to route around.

### Environment setup (needed in every session)

```bash
cd /home/sarath/work/Infosutra/Data-Insights-Hub
export PATH="$HOME/.local/bin:$PATH:$PWD/.local/node-v24.18.0-linux-x64/bin"
```

`pnpm` is invoked as `corepack pnpm`. Python is managed by `uv` inside
`artifacts/api-python`. There is no global `python`/`pip` — always use `uv run`.

### Baseline health check

```bash
corepack pnpm install && corepack pnpm run typecheck && corepack pnpm run build
cd artifacts/api-python && uv run python -c "from app.main import app; print(len(app.openapi()['paths']), 'paths')"
```

Expected: install clean, typecheck `Done`, build `✓ built`, and `43 paths`.

### Do not touch

These are correct and load-bearing.

- **Rule packs are already dynamic.** They live in the `rule_packs` DB table and
  are authored through `RulePackEditor.tsx`. The YAML files in
  `app/rule_packs/` (`facility.yml`, `teachers.yml`, `parents.yml`) are *seeds*
  loaded only when a project has no DB row. Do not "de-hardcode" rule packs.
- **Secret encryption** — `app/core/security.py` (`encrypt_secret`,
  `decrypt_secret`, Fernet from `SHA256(env key)`) and `app/core/config.py`
  (`encryption_key` from `KOBO_CREDENTIALS_ENCRYPTION_KEY` or `SECRET_KEY`).
  Phase 3 changes *where credentials are stored*, never how they are encrypted.
- **Secret masking on the wire.** `MASK = "••••••••"` in
  `app/services/settings.py:23`, with `_is_masked()` at line 34 letting the UI
  send back the mask to mean "unchanged". Preserve this exactly when Kobo
  settings move to per-study endpoints.
- **DQA rule evaluation semantics** in `app/services/dqa_engine.py`. Phase 5
  splits the file; it must not change how any rule evaluates.
- **Report visual output.** Phase 5 moves rendering code; generated
  HTML/PDF/DOCX content must not change.

---

## Phase 0 — Delete dead stacks ✅ COMPLETE

Already done. Recorded so it is not repeated.

Three packages were unused by the running application and were deleted:
`artifacts/api-server/` (abandoned Express backend), `lib/db/` (Drizzle schema,
superseded by SQLAlchemy), `lib/api-zod/` (generated Zod client, never imported).

Supporting cleanup: removed project references from `tsconfig.json`; removed
`db:migrate`/`db:push` from `package.json`; removed the entire `zod` target from
`lib/api-spec/orval.config.ts`; removed `drizzle-orm`/`better-sqlite3` from
`pnpm-workspace.yaml`; removed the `api-server` exclude from
`scripts/sync-to-rpi.sh`; pruned `pnpm-lock.yaml` (41 packages); deleted a stray
`artifacts/api-python/=1.1.0` file from a malformed `uv add`; fixed
`use-form-route-id.ts` (`useRoute` needed an explicit `<{ id: string }>`).

Verified: typecheck passes, build passes, 43 paths.

---

## Phase 1 — Commit a baseline ✅ COMPLETE

**Nothing else in this plan is safe until this is done.**

The repo has one commit (`2de90c1 Initial commit`) and **206 untracked files**.
`artifacts/api-python/` and `artifacts/infosutra/` — the entire working product —
have never been committed. There is currently no rollback path.

### Preconditions

```bash
git log --oneline | wc -l          # expect: 1
git status --porcelain | wc -l     # expect: non-zero
```

### Tasks

1. **Secret audit — ALREADY PERFORMED AND CLEAN.** This was run on
   2026-08-06 against the exact set of files git would commit (257 entries).
   Results:

   - No real `.env` exists; only `.env.example`, whose
     `KOBO_CREDENTIALS_ENCRYPTION_KEY=` is an empty placeholder.
   - `.local/credentials.env` (the live encryption key) exists and **is**
     ignored, via `.gitignore:43` (`.local/`).
   - `data/infosutra.sqlite`, `-shm` and `-wal` **are** ignored, via
     `.gitignore:30` (`/data/*.sqlite*`).
   - Zero matches for token-shaped strings (`Token <hex>`, `sk-…`, `xox…`,
     private-key headers) across all committable files.

   Re-run this only if the working tree changed since then:

   ```bash
   git status --porcelain --untracked-files=all | awk '{print $2}' | \
     xargs -I{} sh -c 'test -f "{}" && rg -l "Token [0-9a-zA-Z]{20,}|sk-[a-zA-Z0-9]{20,}|xox[baprs]-|BEGIN (RSA|OPENSSH|PRIVATE)" "{}" 2>/dev/null' | sort -u
   ```

   Expected: no output. If anything matches, add it to `.gitignore` and
   **stop and report** before committing.

2. **Commit A — the Phase 0 deletion**, so it is legible in history separately
   from the baseline. Stage the existing `D` entries plus the config edits
   (`tsconfig.json`, `package.json`, `pnpm-workspace.yaml`,
   `lib/api-spec/orval.config.ts`, `scripts/sync-to-rpi.sh`, `pnpm-lock.yaml`,
   `.gitignore`).

3. **Commit B — the application baseline**: `artifacts/api-python/` and
   `artifacts/infosutra/`, plus `.env.example`, `docs/`, and any remaining
   untracked support files.

4. Tag the result: `git tag pre-refactor-baseline`.

### Verification

```bash
git status --porcelain          # expect: empty
git log --oneline               # expect: 3 commits, newest = baseline
git tag                         # expect: pre-refactor-baseline
git log -p | rg -c 'Token [0-9a-f]{20,}' || echo "no tokens in history"
```

### Stop and ask

- Any file that looks like a live credential is about to be tracked.
- `.gitignore` does not cover something you believe is sensitive.

---

## Phase 2 — Generate the API contract from FastAPI ✅ COMPLETE

### The problem

Two drifting sources of truth. `lib/api-spec/openapi.yaml` is **hand-maintained**
and declares **24 paths**; FastAPI actually serves **43**. The 19 undeclared
paths are reached through **415 lines of hand-written fetch wrappers**, so every
new endpoint costs three hand-edits and silently rots when one is skipped.

**No route anywhere sets an explicit `operation_id`** — currently zero across 56
handlers in 11 router modules.

### Preconditions

```bash
git status --porcelain          # expect: empty (Phase 1 committed)
cd artifacts/api-python && uv run python -c "from app.main import app; print(len(app.openapi()['paths']))"   # expect: 43
```

### Task 1 — Add `operation_id` to all 56 handlers

Use `camelCase`. Where a generated hook already exists, **keep the existing name**
so no frontend churn is introduced. Existing hooks in use today:
`useGetDashboardSummary`, `useGetDashboardActivity`, `useGetSubmissionTrends`,
`useGetSettings`, `useUpdateSettings`, `useTestKoboConnection`,
`useTestSmtpConnection`, `useSendDailyReport`, `useGetProjects`, `useGetProject`,
`useUpdateProject`, `useSyncProject`, `useSyncProjects`, `useGetSubmissions`,
`useGetSubmission`. Their `operation_id`s must produce exactly these names
(Orval prefixes `use` and capitalises).

| Router | Method + path | Function | `operation_id` |
| --- | --- | --- | --- |
| `health.py` | GET `/healthz` | `healthz` | `healthz` |
| `dashboard.py` | GET `/dashboard/summary` | `dashboard_summary` | `getDashboardSummary` |
| `dashboard.py` | GET `/dashboard/activity` | `dashboard_activity` | `getDashboardActivity` |
| `studies.py` | GET `/studies` | `list_studies` | `getStudies` |
| `studies.py` | POST `/studies` | `create_study` | `createStudy` |
| `studies.py` | GET `/studies/{study_id}` | `get_study` | `getStudy` |
| `studies.py` | PATCH `/studies/{study_id}` | `update_study` | `updateStudy` |
| `studies.py` | DELETE `/studies/{study_id}` | `delete_study` | `deleteStudy` |
| `studies.py` | POST `/studies/{study_id}/projects` | `assign_project` | `assignStudyProject` |
| `studies.py` | DELETE `/studies/{study_id}/projects/{project_id}` | `unassign_project` | `unassignStudyProject` |
| `projects.py` | GET `/projects` | `list_projects` | `getProjects` |
| `projects.py` | POST `/projects/sync` | `sync_projects` | `syncProjects` |
| `projects.py` | GET `/projects/{project_id}` | `get_project` | `getProject` |
| `projects.py` | PATCH `/projects/{project_id}` | `update_project` | `updateProject` |
| `projects.py` | GET `/projects/{project_id}/data-grid` | `project_data_grid` | `getProjectDataGrid` |
| `projects.py` | POST `/projects/{project_id}/sync` | `sync_one_project` | `syncProject` |
| `submissions.py` | GET `/submissions` | `list_submissions` | `getSubmissions` |
| `submissions.py` | GET `/submissions/{submission_id}` | `get_submission` | `getSubmission` |
| `analytics.py` | GET `/analytics/overview` | `analytics_overview` | `getAnalyticsOverview` |
| `analytics.py` | GET `/analytics/projects/{project_id}` | `project_analytics` | `getProjectAnalytics` |
| `analytics.py` | GET `/analytics/trends` | `submission_trends` | `getSubmissionTrends` |
| `insights.py` | GET `/ai/insights` | `list_insights` | `getInsights` |
| `insights.py` | POST `/ai/insights` | `create_insight` | `createInsight` |
| `insights.py` | GET `/ai/insights/{insight_id}` | `get_insight` | `getInsight` |
| `insights.py` | DELETE `/ai/insights/{insight_id}` | `delete_insight` | `deleteInsight` |
| `prompts.py` | GET `/prompts` | `list_prompts` | `getPrompts` |
| `prompts.py` | POST `/prompts` | `create_prompt` | `createPrompt` |
| `prompts.py` | GET `/prompts/{prompt_id}` | `get_prompt` | `getPrompt` |
| `prompts.py` | PUT `/prompts/{prompt_id}` | `update_prompt` | `updatePrompt` |
| `prompts.py` | DELETE `/prompts/{prompt_id}` | `delete_prompt` | `deletePrompt` |
| `reports.py` | GET `/reports` | `list_reports` | `getReports` |
| `reports.py` | POST `/reports` | `create_report` | `createReport` |
| `reports.py` | POST `/reports/dqa-daily` | `create_dqa_daily` | `createDqaDailyReport` |
| `reports.py` | POST `/reports/dqa-final` | `create_dqa_final` | `createDqaFinalReport` |
| `reports.py` | GET `/reports/{report_id}` | `get_report` | `getReport` |
| `reports.py` | GET `/reports/{report_id}/preview` | `preview_report` | `previewReport` |
| `reports.py` | GET `/reports/{report_id}/download` | `download_report` | `downloadReport` |
| `reports.py` | DELETE `/reports/{report_id}` | `delete_report` | `deleteReport` |
| `reports.py` | POST `/reports/{report_id}/generate` | `generate_report` | `generateReport` |
| `reports.py` | POST `/reports/{report_id}/share` | `share_report` | `shareReport` |
| `settings.py` | GET `/settings` | `get_settings` | `getSettings` |
| `settings.py` | PUT `/settings` | `put_settings` | `updateSettings` |
| `settings.py` | POST `/settings/test-kobo` | `test_kobo` | `testKoboConnection` |
| `settings.py` | POST `/settings/test-smtp` | `test_smtp` | `testSmtpConnection` |
| `settings.py` | POST `/settings/send-daily-report` | `send_daily_report` | `sendDailyReport` |
| `settings.py` | POST `/settings/send-dqa-daily-report` | `send_dqa_daily_report` | `sendDqaDailyReport` |
| `dqa.py` | GET `/dqa/summary` | `dqa_summary` | `getDqaSummary` |
| `dqa.py` | GET `/dqa/by-project` | `dqa_by_project` | `getDqaByProject` |
| `dqa.py` | GET `/dqa/flags` | `list_flags` | `getDqaFlags` |
| `dqa.py` | GET `/dqa/enumerators` | `enumerator_stats` | `getDqaEnumerators` |
| `dqa.py` | POST `/dqa/recompute` | `recompute` | `recomputeDqa` |
| `dqa.py` | GET `/dqa/triangulation` | `list_triangulation_views` | `getTriangulationViews` |
| `dqa.py` | GET `/dqa/triangulation/{view_id}` | `triangulation_view` | `getTriangulationView` |
| `dqa.py` | GET `/projects/{project_id}/form-fields` | `project_form_fields` | `getProjectFormFields` |
| `dqa.py` | GET `/projects/{project_id}/rule-pack` | `get_rule_pack` | `getProjectRulePack` |
| `dqa.py` | PUT `/projects/{project_id}/rule-pack` | `put_rule_pack` | `updateProjectRulePack` |

### Task 2 — Type the non-JSON responses

Four handlers need explicit response documentation or the generated client will
mistype them:

- `GET /reports/{report_id}/download` — already `response_model=None`; returns
  `FileResponse` (PDF/DOCX) or a binary `Response`. Add
  `responses={200: {"content": {"application/pdf": {}, "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {}}}}`.
- `GET /reports/{report_id}/preview` — returns `HTMLResponse`. Add
  `response_class=HTMLResponse` and
  `responses={200: {"content": {"text/html": {}}}}`.
- Five handlers that return a bare `dict` with no `response_model`
  (`delete_study`, `unassign_project`, `delete_insight`, `delete_prompt`,
  `delete_report`). Give them a shared `OkResponse` Pydantic model
  (`{"success": bool}`) so the client is typed rather than `unknown`.
- `PUT /settings`, `POST /settings/send-daily-report`, and
  `POST /settings/send-dqa-daily-report` return a `JSONResponse` on their error
  paths. Declare those as documented 400 responses.

### Task 3 — Export the spec from FastAPI

Create `artifacts/api-python/scripts/export_openapi.py`. It must import
`app.main.app`, call `app.openapi()`, and write YAML to
`lib/api-spec/openapi.yaml` with a leading comment marking it generated.

**The no-database constraint is already satisfied — verified, no work needed.**
`init_db()` is called only at `app/main.py:60`, inside the `lifespan` handler,
which does not run on import. Importing `app.main` and calling `app.openapi()`
with `DATABASE_PATH` pointed at a nonexistent file returns 43 paths and creates
no file. Just don't add import-time DB access.

Add to root `package.json`:

```json
"api:spec": "cd artifacts/api-python && uv run python scripts/export_openapi.py",
"api:client": "pnpm run api:spec && cd lib/api-spec && pnpm exec orval",
"api:spec:check": "pnpm run api:spec && git diff --exit-code lib/api-spec/openapi.yaml"
```

### Task 4 — Normalise query-parameter casing

There are **16** hand-written `alias="…"` query-parameter declarations scattered
across `routers/dqa.py` (11), `routers/reports.py` (2), `routers/submissions.py`
(2), and `routers/projects.py` (1). Response bodies are already
camelCase via `app/schemas/common.py` (`alias_generator=to_camel`,
`serialize_by_alias=True`). Replace the per-parameter aliases with shared
Pydantic query models using the same generator, so the convention is declared
once.

### Task 5 — Regenerate the client and delete the wrappers

Run `pnpm run api:client`, then migrate every call site and delete the three
wrapper files. Complete call-site inventory:

**`src/lib/dqa-api.ts`** → `Dashboard.tsx:51`; `DqaDashboard.tsx:94,99,108,118,125,130`;
`SubmissionDetail.tsx:169,174`; `RulePackEditor.tsx:129,134,178,179`;
`SubmissionsGrid.tsx:143`. Types imported: `DqaFlag`, `FormField`,
`TriangulationLink`, `GridCell`, `GridColumn`, `GridFlagRef`, `GridRow` — all
replaced by generated schema types.

**`src/lib/reports-api.ts`** → `Reports.tsx:29,37,51,64` and the `Report` type at
line 19. `reportsApi.share` has **no call sites** — drop it.

**`src/lib/studies-api.ts`** → `Studies.tsx:35,112,114,137,152,165`;
`StudyProvider.tsx:35`. `studiesApi.get` has **no call sites** — drop it.

`previewUrl(id)` and `downloadUrl(id, format)` are **not fetches** — they build
URLs for `<a href>` elements at `Reports.tsx:172,178,184`. Keep them as a small
URL helper (e.g. `src/lib/report-urls.ts`). Do not force them through the
generated client.

Also replace the one raw `fetch` at **`Settings.tsx:630`**
(`POST /api/settings/send-dqa-daily-report`) with the newly generated
`useSendDqaDailyReport` hook.

Migration pattern — replace manual wrapping:

```ts
// before
const q = useQuery({ queryKey: ["dqa-summary", projectId], queryFn: () => dqaApi.summary(projectId, studyId) });
// after
const q = useGetDqaSummary({ projectId, studyId });
```

Mutations keep their existing invalidation keys, following
`Projects.tsx:27–35`.

### Verification

```bash
corepack pnpm run api:spec
rg -c '^  /' lib/api-spec/openapi.yaml            # expect: 43
rg -l 'dqa-api|reports-api|studies-api' artifacts/infosutra/src   # expect: no output
rg -n 'fetch\(' artifacts/infosutra/src --glob '!*/generated/*'   # expect: no output
corepack pnpm run typecheck && corepack pnpm run build
corepack pnpm run api:spec:check                  # expect: clean exit
```

Then start the app and manually confirm: DQA dashboard loads summary, flags,
enumerators and a triangulation view; reports list loads; PDF and DOCX download;
rule-pack editor loads and saves.

### Stop and ask

- An `operation_id` in the table above would rename a hook currently in use in a
  way that is not a pure rename.
- The generated client cannot express the download endpoint's binary response.

---

## Phase 3 — Rebuild the data model ✅ COMPLETE

Data may be dropped, so this is a clean rebuild, not a migration.

### Problems

1. **Kobo credentials are global.** `AppSettings` is a singleton row
   (`id="singleton"`) holding one `kobo_token_encrypted`, one `kobo_server_url`,
   one `kobo_username`. The requirement is one API key **per study**. Today
   `sync_all_projects` (`kobo_sync.py:256`) calls `client.list_assets()` and
   syncs *every survey asset visible to that one token*, with no study filter.
2. **The study↔project relationship is stored twice** — as `Study.form_map` JSON
   (`[{"toolCode","projectUid","label"}]`) and `Study.targets` JSON
   (`{"T1": 440}`), *and* as real `Project.study_id` + `Project.tool_code`
   columns. Nothing keeps them consistent. The JSON copy is why triangulation
   needs its seed-UID fallback.
3. **`Submission.project_name` is denormalized** and strictly derivable through
   the `project_id` FK.
4. **`AppSettings` mixes four concerns** — Kobo connection, SMTP, AI provider,
   and scheduled reports. The DQA digest is bolted on via a single
   `dqa_daily_study_id` column, so only one study can ever be scheduled.
5. **`Report.project_ids` / `project_names`** are parallel JSON arrays that must
   be kept index-aligned by hand.
6. **Migrations are an ad-hoc `ALTER TABLE` list.** `app/db/schema_migrate.py`
   holds 14 hand-written additive columns applied by `ensure_schema()` after
   `create_all()` (called from `app/db/session.py:38,41`). It can only add
   columns and has no version tracking.
7. **`kobo_auto_sync` and `kobo_sync_interval_hours` are dead config.** They are
   stored, surfaced in the settings UI, and read by nothing. The only scheduler
   (`app/main.py:40–54`, 30-second loop) handles email digests, not sync.

### Target schema

- **`Study`** — identity and window only: `id`, `name`, `description`,
  `start_date`, `end_date`, `timezone`. **Drop `form_map` and `targets`.**
- **`StudyCredential`** *(new)* — `study_id` FK, `kobo_server_url`,
  `kobo_token_encrypted`, `kobo_username`, `connected`, `last_tested_at`.
  Reuse `encrypt_secret`/`decrypt_secret` unchanged.
- **`StudyTool`** *(new)* — replaces `form_map` + `targets`: `study_id` FK,
  `code` (the study's own label), `label`, `target_count`, `sort_order`.
  Unique on `(study_id, code)`.
- **`Project`** — keep `study_id`; replace the free-text `tool_code` string with
  a `study_tool_id` FK.
- **`Submission`** — drop `project_name`. Keep `enumerator`, `form_id`,
  `form_name`; they come from submission payloads and are not reliably
  derivable. Note as a follow-up, do not fix here.
- **`AppSettings`** — narrow to genuinely global: SMTP, AI, organization,
  locale. Kobo fields move to `StudyCredential`. **Drop `kobo_auto_sync` and
  `kobo_sync_interval_hours`** (dead) — and remove them from the settings UI in
  the same commit.
- **`ReportSchedule`** *(new)* — replaces the `dqa_daily_*` columns:
  `study_id`, `report_type`, `enabled`, `time`, `timezone`, `recipients`,
  `last_sent_on`.
- **`Report`** — replace `project_ids`/`project_names` with a `report_projects`
  association table.

Also change the default `organization_name` from `"Sight Savers 2026"` to a
neutral value.

### Tasks

1. Add **Alembic** to `artifacts/api-python`, configured against the metadata in
   `app/db/base.py`.
2. Split `app/db/models/__init__.py` (278 lines) into one module per aggregate —
   `study.py`, `project.py`, `submission.py`, `dqa.py`, `reporting.py`,
   `settings.py` — re-exported from `__init__.py`. Apply the target schema.
3. Generate a **single initial Alembic revision**. There is no upgrade path to
   write because data is being dropped.
4. **Delete `app/db/schema_migrate.py`** and its call site in
   `app/db/session.py:38,41`. Startup runs `alembic upgrade head` instead of
   `create_all()` + `ensure_schema()`.
5. Rework credential resolution. `_configured_client` (`kobo_sync.py:92–99`) is
   the single construction point for sync and currently resolves once at the top
   of `sync_all_projects` (`:256`) and `sync_project` (`:296`) — good structure,
   just wrong source. Change it to take a study and load `StudyCredential`.
   `KoboClient` itself (`app/integrations/kobo.py`) needs **no change**; it is
   already credential-agnostic.
6. Decide sync scope per study. `sync_all_projects` must no longer sync every
   visible asset — it syncs the assets belonging to the study whose credential
   is in use.
7. Update `app/services/settings.py` — `to_settings_out` (Kobo block at lines
   51–58), `get_kobo_token` (129–135), `update_settings` (Kobo block 162–185),
   `test_kobo` (248–271), and `clear_undecryptable_secrets` (105–126, called from
   `app/main.py:63–71`). Kobo endpoints become study-scoped; keep the masking
   behaviour identical.
8. Update `app/services/local_reset.py` (`_snapshot_settings` at 61–68,
   `_restore_settings` at 71–80) for the new schema.
9. **Fix the `Submission.project_name` fallout.** Dropping the column breaks
   **eight** call sites. All must be rewritten to reach the name through the
   `project_id` FK (`Project.name`):

   | File:line | Use |
   | --- | --- |
   | `routers/analytics.py:30–31` | `select(Submission.project_name)` + `group_by` — rewrite as a join on `Project.name` |
   | `routers/submissions.py:27` | serializes `row.project_name` |
   | `routers/dashboard.py:87–88` | activity feed message and field |
   | `routers/dqa.py:76` | `submission.project_name` on a flag |
   | `services/dqa_engine.py:187` | `"projectName": row.project_name` |
   | `services/triangulation.py:79` | `_link()` builds `TriangulationLink.project_name` |
   | `services/triangulation.py:175` | fallback when `institution_name` is empty |
   | `services/kobo_sync.py:201` | **the write** — `row.project_name = get_asset_name(asset)`; just delete it |

   Do **not** confuse these with the unrelated `Project.name`,
   `Insight.project_name`, or `Report.project_names`, which all stay.
   Re-check with `rg -n 'project_name' app | rg -v 'schemas/'` before finishing.

10. Re-run `pnpm run api:client` (one command, thanks to Phase 2) and fix the
    frontend types.

### Verification

```bash
cd artifacts/api-python
rm -f ../../data/infosutra.sqlite
uv run alembic upgrade head
uv run python -c "from app.main import app; print(len(app.openapi()['paths']))"
rg -n 'ensure_schema|schema_migrate' app        # expect: no output
rg -n 'form_map|targets' app/db/models          # expect: no output
cd ../.. && corepack pnpm run api:client && corepack pnpm run typecheck && corepack pnpm run build
```

Then manually: create two studies with **different** Kobo tokens and confirm each
syncs only its own forms.

### Stop and ask

- Dropping `kobo_auto_sync`/`kobo_sync_interval_hours` is unwanted because
  auto-sync is meant to be implemented rather than removed.

*(The credential-sharing question is settled: one account per study. Do not
re-open it.)*

---

## Phase 4 — Make triangulation study-defined ✅ COMPLETE

This is the phase with the most hidden design content. Read this section fully
before writing code.

### The problem

`app/services/triangulation.py` (452 lines) hardcodes one study's design:

- Imports `SIGHTSAVERS_2030_FORMS` and `SIGHTSAVERS_2030_ID` from
  `app/services/studies.py` and builds `_SEED_UID` from them (line 21).
- `_project()` (line 110) defaults `study_id` to `SIGHTSAVERS_2030_ID` (line 113)
  and falls back to seed UIDs (line 127). **A second study therefore reads the
  first study's data.** This is a correctness bug, not untidiness.
- Views are three hardcoded functions resolving inputs by literal tool code:
  `_project(db, "T1")` facility, `"T2"` teachers, `"T3"` parents.
- `TriangulationRow` in `app/schemas/dqa.py:107–126` is a union of every view's
  fields with study-specific names (`udise`, `school_name`, `teacher_has_cwd`,
  `parent_reports_disability`, `school_meetings`, `parent_attended_pta`, …). The
  study vocabulary is baked into the **wire contract**, and
  `DqaDashboard.tsx` renders those exact field names — the triangulation tab
  spans lines 500–681, with the row rendering at 612–680.

So this is a full-stack change: model → evaluator → wire schema → UI.

### The abstraction already exists

Rule packs provide exactly the indirection needed. Every pack has `join_key`
(all three seeds use `udise`) and a `fields:` alias→physical-field map.
`get_value(data, pack, alias)` resolves through it.

**The hardcoding is precisely where the code bypasses the alias layer:**

| Location | Bypass | Fix |
| --- | --- | --- |
| `triangulation.py:214,221` | `find_field_value(data, "P5")` raw | add alias `reports_disability: P5` to `parents.yml` |
| `TR1_PRACTICES` `observe_field` | raw `CO1`–`CO8` | add observation aliases to `teachers.yml` |
| `triangulation.py:290` | falls back to raw `"D4"` | `practice_d4` alias already exists — drop the fallback |

Aliases to add — `parents.yml`: `reports_disability: P5`. `teachers.yml`:
`observe_front_seating: CO1`, `observe_differentiated: CO2`,
`observe_multi_sensory: CO3`, `observe_peer_group: CO4`,
`observe_adapted_materials: CO8`.

### The two view kinds

One generic format cannot express all three views without becoming a programming
language. TR-3 and TR-5 are *cross-form entity joins*; TR-1 is a *within-form
claim-versus-observation matrix* with no join at all. **Implement two kinds.**

**Kind A — `cross_form_join` (covers TR-3, TR-5).** Join key comes from each
participant's rule pack `join_key`.

```yaml
kind: cross_form_join
code: TR-5
title: CWD identification consistency
description: >
  Where parents report a child with disability at an institution,
  teachers there should report having CWD in class.
participants:
  - role: facility
    tool: T1
    pick: { then: latest }
    derive:  { school_name: { alias: institution_name, as: text } }
  - role: teacher
    tool: T2
    # prefer a contradicting submission, else newest
    pick: { prefer: { alias: has_cwd, value: false }, then: latest }
    reduce:  { has_cwd: { alias: has_cwd, as: bool_any } }
  - role: parent
    tool: T3
    pick: { prefer: { alias: reports_disability, value: true }, then: latest }
    reduce:  { reports_disability: { alias: reports_disability, as: bool_any } }
mismatch:
  all:
    - { is_true:  parent.reports_disability }
    - { is_false: teacher.has_cwd }
columns:
  - { key: join_key,                    label: UDISE,                     as: text }
  - { key: facility.school_name,        label: School,                    as: text }
  - { key: teacher.has_cwd,             label: Teacher reports CWD,       as: yes_no }
  - { key: parent.reports_disability,   label: Parent reports disability, as: yes_no }
```

TR-3 uses the same kind, adding a `computed` block:

```yaml
participants:
  - role: facility
    tool: T1
    pick: { then: latest }
    derive:
      school_name:   { alias: institution_name, as: text }
      meetings:      { alias: meetings_held,    as: int_or_zero }
      cwd_discussed: { alias: cwd_discussed,    as: bool }
  - role: parent
    tool: T3
    pick: { then: latest }
    reduce:
      attended_pta: { alias: attended_pta, as: bool_any }
      pta_issues:   { alias: pta_issues,   as: bool_any }
computed:
  facility.active:
    all: [ { gt: [facility.meetings, 0] }, { is_true: facility.cwd_discussed } ]
mismatch:
  all:
    - { is_true: facility.active }
    - { not: { all: [ { is_true: parent.attended_pta }, { is_true: parent.pta_issues } ] } }
```

Required primitives, and no more: reducers `bool_any`, `text`, `bool`,
`int_or_zero`; picks `latest` and `prefer(alias,value) then latest`; predicates
`is_true`, `is_false`, `all`, `not`, `gt`.

**Kind B — `claim_vs_observation` (covers TR-1).** Single tool, one row per
submission.

```yaml
kind: claim_vs_observation
code: TR-1
title: "Teacher practice: claimed vs observed"
tool: T2
claim_alias: practice_d4
observation:
  observed_values: ["1", "2"]     # clearly / partially observed
  no_opportunity_value: "4"       # excluded from the denominator
  gap_value: "3"                  # claimed but not observed → gap
items:
  - { id: front_seating,      label: "Appropriate / front seating",       claim_codes: [e],    observe_alias: observe_front_seating }
  - { id: differentiated,     label: "Differentiated tasks / materials",  claim_codes: [a],    observe_alias: observe_differentiated }
  - { id: multi_sensory_visual, label: "Visual supports / multi-sensory", claim_codes: [b, c], observe_alias: observe_multi_sensory }
  - { id: peer_group,         label: "Peer support / inclusive group work", claim_codes: [d, f], observe_alias: observe_peer_group }
  - { id: adapted_materials,  label: "Adapted materials / assistive use", claim_codes: [h],    observe_alias: observe_adapted_materials }
```

### Behaviour that must be preserved exactly

The current TR-1 gap condition (lines 310–313) is written redundantly:

```python
if claimed and not observed and str(obs_val or "").strip() in {"3", "2", "1"}:
    if not observed:
        gap += 1
```

`observed` is true iff `obs_val ∈ {"1","2"}`, so the outer condition reduces to
`claimed and obs_val == "3"`, and the inner `if` is always true. **The intended
semantics are: `gap += 1` when the practice is claimed and the observation value
is exactly `"3"`.** Implement that. Do not "improve" it.

Two more to carry over verbatim:

- Denominator: a practice counts toward `n` only when `obs_val != "4"`
  (line 300).
- `concordance_pct = max(0, 100 - |claimed_pct - observed_pct|)` (line 338). The
  code's own comment calls this approximate, and the `denom` variable at line 336
  is computed but unused. Preserve the formula; drop the unused variable.

### Generalise the wire schema

Replace the field-union `TriangulationRow` with a generic shape:

```python
class TriangulationCell(CamelModel):
    key: str
    label: str
    value: Any
    kind: str          # "text" | "bool" | "number" | "list"

class TriangulationRow(CamelModel):
    key: str                                      # the join key value
    cells: list[TriangulationCell]
    links: dict[str, TriangulationLink | None]    # role -> link
    mismatch: bool = False

class TriangulationViewOut(CamelModel):
    id: str
    title: str
    description: str | None = None
    columns: list[TriangulationColumn]
    rows: list[TriangulationRow]
    mismatch_count: int
    practices: list[TriangulationPracticeStat] = []   # kind B only
```

`TriangulationLink` and `TriangulationPracticeStat` stay as they are.

### Tasks

1. Add a **`TriangulationView`** model: `study_id` FK, `code` (study-defined,
   not restricted to `TR-*`), `title`, `description`, JSON `definition`.
2. Add the missing rule-pack aliases listed above.
3. Rewrite `triangulation.py` as two evaluators over a `definition`. **Delete the
   `SIGHTSAVERS_2030_ID` default and the `_SEED_UID` fallback** — a request
   without a resolvable study returns 4xx, never another study's data.
4. Move `SIGHTSAVERS_2030_*` out of `app/services/studies.py` into `app/seeds/`,
   and express TR-1/TR-3/TR-5 as seed definitions in the new format.
   `seed_default_study()` becomes an explicit opt-in dev command, not a startup
   call.
5. Update `dqa_final_report.py` (17 `TR-` references) and `report_charts.py`
   (2) to iterate over the study's defined views instead of naming them.
6. Rewrite the triangulation tab in `DqaDashboard.tsx` (lines 500–681) as one
   generic table driven by `columns` + `cells`, replacing the three hardcoded
   per-view renderings. The practices table at 528–557 stays, but renders only
   for `claim_vs_observation` views.
7. Add a triangulation-view editor mirroring `RulePackEditor.tsx`.

### Verification

```bash
cd artifacts/api-python
rg -i 'sightsavers' app          # expect: only app/seeds/*
rg '"T1"|"T2"|"T3"' app          # expect: only app/seeds/*
```

Behavioural check — **capture before you start**: with the seeded study, save
the JSON of all three views, then confirm after the rewrite that
`mismatch_count`, row count, and per-practice stats are identical.

```bash
# BEFORE the rewrite
for v in TR-1 TR-3 TR-5; do
  curl -s "http://localhost:8000/api/dqa/triangulation/$v?studyId=study-sightsavers-2030" \
    > "/tmp/tri-before-$v.json"
done
# AFTER — compare mismatchCount and row counts
```

Then create a second study with two tools and one custom view, and confirm it
returns its own data and that requesting a view with no study id returns 4xx.

### Stop and ask

- A required view cannot be expressed by either kind without adding a new
  primitive. Report which primitive and why before inventing one.
- The before/after comparison differs. Do not adjust the expected values to
  match — report the difference.

---

## Phase 5 — Break up the god modules ✅ COMPLETE

Pure structural refactor. **No behaviour change.**

### Current state

| Module | Lines | Concerns |
| --- | --- | --- |
| `services/dqa_daily_report.py` | 1193 | stats, HTML, plaintext, PDF, DOCX, persistence, paths |
| `services/dqa_final_report.py` | 985 | same, for the final report |
| `services/dqa_engine.py` | 878 | rule loading, evaluation, flag persistence |
| `routers/dqa.py` | 449 | routing plus query logic |
| `services/report_docx.py` | 403 | DOCX for both report types |

Backend is ~9,750 lines, so the two report modules alone are 22% of it.

They are entangled, not merely similar. `dqa_final_report.py` reaches into
`dqa_daily_report` for two different kinds of thing:

- `daily.build_daily_dqa_stats(...)` (line 36) — the final report is built *on
  top of* daily's stats computation.
- `daily.pdf_path_for(...)` / `daily.docx_path_for(...)` (lines 952–954) —
  shared storage infrastructure.

A feature module is serving as both a domain library and an infrastructure
module for its sibling. Both files also do a function-local
`from app.services import report_docx` (`dqa_final_report.py:946`,
`dqa_daily_report.py:1072`) to dodge a circular import.

### Target layout

```
app/
  routers/        HTTP only — parse, delegate, serialize
  services/       orchestration / use-cases
  domain/         pure logic, no DB and no I/O
    dqa/          rule evaluation, triangulation evaluation
    reporting/    stats computation
  rendering/      html.py, pdf.py, docx.py, plaintext.py, charts.py
  repositories/   all SQLAlchemy queries
  integrations/   kobo.py, smtp.py, ai.py
  seeds/          study seeds (from Phase 4)
```

### Tasks

1. **Capture the behavioural baseline first.** Generate one daily and one final
   report; save the HTML, plaintext, and extracted text of the PDF and DOCX. The
   whole phase depends on this comparison being real.
2. Extract path helpers (`reports_dir`, `pdf_path_for`, `docx_path_for`) into
   `app/services/report_storage.py`, ending the daily→final coupling.
3. Extract stats computation into `app/domain/reporting/` as pure functions
   taking loaded data and returning the stats dict — no `Session` parameter.
4. Move renderers into `app/rendering/`: `report_docx.py`, `report_format.py`,
   `report_charts.py`, plus the HTML/plaintext/PDF renderers.
5. Reduce each `dqa_*_report.py` to a thin orchestrator — load, compute, render,
   persist. Target under 150 lines each.
6. Collapse the daily/final duplication into a shared pipeline parameterised by
   report type.
7. Extract query logic from `routers/dqa.py` into repositories.
8. Split `dqa_engine.py` into rule loading, pure evaluation, and flag
   persistence.
9. Remove both function-local `report_docx` imports.

### Verification

```bash
cd artifacts/api-python
find app -name '*.py' | xargs wc -l | sort -rn | head -5    # expect: max < 400
rg -n 'from app.services import report_docx' app            # expect: only module-level
rg -n 'sqlalchemy' app/domain                               # expect: no output
```

Then regenerate both reports and diff against the Task 1 baseline. HTML and
plaintext must be identical; PDF/DOCX text content must be identical.

### Stop and ask

- The baseline outputs differ after refactoring and the cause is not obvious.
- Splitting a module would require changing rule evaluation or report content.

---

## Phase 6 — Finish the study workspace ✅ COMPLETE

**Scope correction: most of this already exists.** `StudyProvider.tsx`
(`src/components/study/`) already holds `activeStudyId`, persists it to
`localStorage` under `infosutra.activeStudyId`, auto-selects the first study, and
exposes `useStudy()` / `useOptionalStudy()`. `RequireActiveStudy.tsx` gates
study-scoped pages. Ten files already consume the context, including `App.tsx`,
`Sidebar.tsx`, `Dashboard.tsx`, `DqaDashboard.tsx`, `Reports.tsx`, `Projects.tsx`,
`Settings.tsx`, `Studies.tsx`.

So do **not** build a study selector. What is actually missing:

1. **URL reflection.** Study selection is `localStorage`-only, so links are not
   shareable and a shared URL opens whatever study the recipient last used. Put
   the active study in the URL and treat `localStorage` as the fallback default.
2. **Cross-study portfolio view.** Global scoping removes cross-study comparison;
   a dedicated Portfolio page is the deliberate exception that restores it.
3. **Per-study Kobo settings UI**, matching the Phase 3 schema. Move the Kobo
   block out of the global Settings page; SMTP, AI, and organization stay global.
   Remove the `kobo_auto_sync` / `kobo_sync_interval_hours` controls, which are
   backed by nothing.
4. **Per-study report scheduling**, backed by the Phase 3 `ReportSchedule` table,
   replacing the single `dqa_daily_study_id`.
5. **Wire the four stub pages to real data.** `Analytics.tsx`, `AiInsights.tsx`,
   `PromptTemplates.tsx`, and `DataExplorer.tsx` currently render mock data and
   make no API calls. The decision is to wire all four — but the work is very
   uneven, so treat them as four separate tasks, not one.

   | Page | Backend today | Work required |
   | --- | --- | --- |
   | `PromptTemplates.tsx` | `/prompts` full CRUD exists | Pure wiring |
   | `DataExplorer.tsx` | `/projects/{id}/data-grid`, `/submissions` exist | Pure wiring |
   | `Analytics.tsx` | 3 endpoints exist but are **not study-scoped** | Backend change first |
   | `AiInsights.tsx` | `/ai/insights` is **CRUD-only** | New feature |

   **Analytics** — `analytics_overview` (`analytics.py:24`) and
   `submission_trends` (`:95`) take no `studyId` and aggregate across every
   submission in the database. Add study scoping before wiring the page, or it
   will show cross-study totals inside a study workspace. Note this overlaps
   Phase 3 task 9, which already has to rewrite `analytics_overview`.

   **AI Insights** — the `insights` table and its four endpoints only store and
   retrieve rows. **Nothing generates an insight.** The AI plumbing does exist
   and works: `app/integrations/openrouter.py` (`chat_completion`) is already
   used by `dqa_daily_report.py:19` and `dqa_final_report.py:395,459`. So this
   task is "add an insight-generation endpoint reusing the existing OpenRouter
   integration, scoped to a study" — a genuine new feature, not wiring. Size it
   accordingly and consider splitting it into its own phase.

### Verification

- Switching study updates every scoped tab without a reload.
- Copying a URL and opening it in a fresh profile shows the same study.
- No page merges two studies' data except Portfolio.
- Adding a study plus its Kobo key from the UI is sufficient to sync its forms,
  with no code change or manual DB edit.

---

## Phase 7 — Guardrails ✅ COMPLETE

There are currently **no Python tests** and no Python linter. Without this phase
the earlier work decays.

### Tasks

1. Add `pytest` and `ruff` to `artifacts/api-python`; configure ruff in
   `pyproject.toml`.
2. Tests for what is most likely to regress:
   - DQA rule evaluation against a fixture rule pack.
   - Both triangulation kinds against a fixture study with study-defined tools,
     including the TR-1 gap rule (`claimed and obs_val == "3"`) and the
     `obs_val == "4"` denominator exclusion.
   - Report stats, using the Phase 5 snapshots.
   - An architecture test asserting `app/domain/` never imports `sqlalchemy`.
   - Timezone handling for `generated_at`, guarding the naive-UTC bug already
     fixed once in this codebase.
   - A test that a study cannot read another study's submissions through
     triangulation — the Phase 4 correctness fix.
3. Add a `test` script; include Python tests in the root `build`.
4. Add `api:spec:check` from Phase 2 to the same script.

### Verification

```bash
corepack pnpm test          # expect: Python + frontend checks pass
cd artifacts/api-python && uv run ruff check .
```

---

## Sequencing

| Phase | Depends on | Risk | Behaviour change |
| --- | --- | --- | --- |
| 0 · Delete dead stacks ✅ | — | done | no |
| 1 · Git baseline ✅ | 0 | done | no |
| 2 · Generated API contract ✅ | 1 | done | no |
| 3 · Schema rebuild ✅ | 2 | done | yes — per-study credentials |
| 4 · Study-defined triangulation ✅ | 3 | done | yes — no silent fallback |
| 5 · Break up god modules ✅ | 4 | done | no |
| 6 · Finish study workspace ✅ | 3, 4 | done | yes |
| 7 · Guardrails ✅ | 5 | done | no |

All phases complete. Historical sequencing rationale:

- Phase 2 before Phase 3: once the spec and client are generated, schema changes
  propagate to the frontend with one command instead of three hand-edits.
- Phases 3 and 4 were the behaviour-changing, high-risk steps; their "Stop and
  ask" conditions were the point of those phases, not friction to route around.
