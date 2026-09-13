# Remove Forms tab — implementation handover

Information architecture change: **Forms is not a study nav destination**. Dashboard is the study pulse; Studies owns assignment/pull; `/forms/:id` is the instrument drill-down (submissions). Do not re-litigate this. Do not paste the Forms table onto Dashboard.

Verify against: `http://localhost:5173/?study=study-aeeff71f3eb1` (CmF Baseline Study). After the change, `/forms` must not appear in the sidebar.

## Decision (locked)

| Job | Surface |
|---|---|
| Study pulse (volume, quality, trend) | **Dashboard** (`/`) |
| Assign tool codes, pull/unassign forms | **Studies** (`/studies`) |
| Study-level Sync from Kobo | **Dashboard** header (outline) |
| Per-instrument records | **`/forms/:id`** (existing ProjectDetail — submissions-heavy) |
| Quality investigation | **Data Quality** (`/dqa?projectId=…`) |

Remove the **Forms index** from navigation and from product copy. Keep the **routes** `/forms/:id`, `/forms/:id/submissions`, `/forms/:id/rules` (and legacy `/projects/…`).

## Click targets (intent-matched)

Do **not** send every form name to submissions.

| Dashboard control | Today | After |
|---|---|---|
| Data Quality by Project — form name | `/dqa?projectId=` | **Keep DQA** (`/dqa?projectId=…`, preserve `?study=`) |
| Data Quality — “Open Data Quality” | `/dqa` | **Keep** `/dqa` |
| Top Forms by Volume — row | `/forms/:id` | **`/forms/:id`** (already submissions workspace; preserve `?study=`) |
| Top Forms — “View all” | `/forms` | **Remove** the “View all” link. No Forms index. |
| Study Forms KPI card | not a link | Leave unlinked (or scroll to the DQA table). Do **not** link to `/forms` or `/dqa`. |

Red/amber **numbers** in the DQA table stay as numbers (not extra links) unless they already link.

## Sync from Kobo on Dashboard

Move the **study-level** sync control from the Forms index to Dashboard.

- Place it in the Dashboard `Header` `action` slot: **outline** `Button`, label **Sync from Kobo**, same `useRunStudySync` / `useSyncProjectsPending` pattern as `Projects.tsx`.
- Disable when no `activeStudyId` or while pending. Spin the refresh icon while pending.
- Keep it **secondary**. Do not make it `bg-primary`. Do not replace the LIVE chip or the date range.
- Suggested order: date range → **Sync from Kobo** → LIVE.
- After sync, show the same success/partial banner already used on Forms (`syncData`: forms synced, submissions fetched, errors, unassigned → link to **Studies** not Forms).
- Empty-state copy on Dashboard: “Sync from Kobo…” / “assign on Studies” — never “Sync from Forms”.
- **Keep** Studies pull-forms for first-time setup.
- **Keep** form page **Sync Data** (per instrument).
- **Do not** add a third study-level Sync to the sidebar.

## Remove Forms as a tab

1. `Sidebar.tsx` — delete `{ name: "Forms", href: "/forms", … }` from `studyNavigation`. Leave Dashboard first.
2. `RequireActiveStudy.tsx` — change “Sync forms” (`href="/forms"`) to **Studies** (`href="/studies"`) or drop the second button if Studies is already the primary CTA.
3. Grep and retarget remaining **`href="/forms"`** (index only). Do **not** retarget `/forms/:id…`.

Known index links:

- `Dashboard.tsx` — “View all” (remove)
- `RequireActiveStudy.tsx` — “Sync forms”
- Empty-state strings: “Sync from Forms…”

`Studies.tsx` links to `/forms/${p.id}` stay (instrument page).

## Forms index page (`/forms`)

`App.tsx`: `/forms` and `/projects` (index only) **redirect** to `/` (Dashboard), preserving `?study=` and any other search params. Bookmark `/forms?study=…` must land on Dashboard.

Do **not** delete `ProjectDetail`, `ProjectSubmissions`, `RulePackEditor`, or `/forms/:id…` / `/projects/:id…`.

## Cleanup (required — do this in the same change)

Do not leave a dead Forms catalog, unused CSS, or “Sync from Forms” copy. After the redirect is in, **delete leftover index code**.

### Delete

| Item | Why |
|---|---|
| `artifacts/infosutra/src/pages/projects/Projects.tsx` | Entire file is the Forms **index**. Nothing else should import it after the redirect. |
| `FormsPage` import and `component={FormsPage}` in `App.tsx` | Replaced by a tiny redirect component (inline in `App.tsx` is fine). |
| `.forms-table-row*` rules in `artifacts/infosutra/src/index.css` | Only used by the deleted index table. Also delete any leftover `.form-list-row*` if still present. |
| Dashboard “View all” link to `/forms` | No index. |
| `RequireActiveStudy` “Sync forms” → `/forms` | Retarget or remove (Studies is enough). |
| Unused `FolderGit2` import in `Sidebar.tsx` if it is only used for the Forms nav item | Dead import. |

### Grep and fix (index only)

Run from `artifacts/infosutra`:

```
rg -n "from './pages/projects/Projects'|from \"@/pages/projects/Projects\"|FormsPage|/forms\"|/forms'|Sync from Forms|View all" src
rg -n "forms-table-row|form-list-row" src
```

Retarget or delete **exact** `/forms` and `/projects` (no `:id`). Leave `/forms/${id}`, `/forms/:id`, `/projects/:id`.

Copy to rewrite (do not leave stale product language):

- `Dashboard.tsx`: “Sync from Forms, assign them to a study…” → Sync from Kobo / assign on Studies
- `Dashboard.tsx`: “No forms yet. Sync from Forms…”
- Help dialogs or empty states that tell users to open the Forms tab

### Do not delete

- `ProjectDetail.tsx`, `ProjectSubmissions.tsx`, `SubmissionDetail.tsx`, `RulePackEditor.tsx`
- `lib/use-form-route-id.ts`
- Studies links to `/forms/${p.id}`
- Form-page **Sync Data** and DQA rules link
- `docs/forms-layout-implementation.md` (historical; index is retired)
- Canvas `forms-layout-vision-mock.canvas.tsx` (historical mock)

### Cleanup verify

- `Projects.tsx` is gone; `tsc` / app build has no missing-import errors
- `index.css` has no `forms-table-row` / `form-list-row`
- `rg FormsPage` and `rg "href=\"/forms\""` in `src` return no index hits (hrefs with an id are OK)
- Sidebar has no unused icon import from the removed nav item

## Dashboard quality table (small, required)

Add **tool code** if it is cheap from existing project/DQA payloads so T1–T8 still scan without a Forms tab. If `ProjectDqaStat` has no `toolCode`, join `useGetProjects()` by `projectId` and show a mono chip beside the name. Missing code: muted “—”. Do **not** rebuild the full Forms table (no Last/Open·DQA/sort chips).

Preserve `?study=` on every Dashboard → form/DQA link (`useStudy().activeStudyId`).

## Copy

Replace user-facing “Forms tab” / “Sync from Forms” / “View all” (to `/forms`) with Dashboard or Studies language.

Sidebar study footer (“9 forms · 824 submissions”) can stay — that is a count, not a nav item.

## Out of scope

- Redesigning DQA, Studies, or form detail
- Merging the Forms table into Dashboard
- Changing DQA-table name clicks to submissions
- New APIs
- Canvas mock updates
- Removing `/forms/:id` routes

## Verify

1. Sidebar on `/?study=study-aeeff71f3eb1` — no Forms item. Dashboard, Data Quality, … unchanged.
2. Dashboard header — outline **Sync from Kobo** next to the date range; LIVE still visible.
3. DQA-by-project form name → `/dqa?projectId=…&study=…`.
4. Top Forms row → `/forms/:id?study=…` (submissions workspace). No “View all”.
5. `/forms?study=study-aeeff71f3eb1` redirects to Dashboard with study preserved.
6. Studies still opens `/forms/:id` for an assigned form.
7. Empty study: RequireActiveStudy does not send people to `/forms`.
8. After sync from Dashboard, toast/banner works; unassigned CTA goes to Studies.
9. Cleanup verify above: no `Projects.tsx`, no `FormsPage`, no index `/forms` hrefs, no dead CSS.

## Suggested file list

- `artifacts/infosutra/src/components/layout/Sidebar.tsx` — remove nav item + unused import
- `artifacts/infosutra/src/pages/dashboard/Dashboard.tsx` — Sync, link map, copy
- `artifacts/infosutra/src/components/study/RequireActiveStudy.tsx`
- `artifacts/infosutra/src/App.tsx` — redirect `/forms` and `/projects` → `/`; drop `FormsPage`
- **Delete** `artifacts/infosutra/src/pages/projects/Projects.tsx`
- **Delete** `.forms-table-row*` (and leftover `.form-list-row*`) in `src/index.css`

Do not change `docs/forms-layout-implementation.md` (historical; that page is being retired as a nav surface).
