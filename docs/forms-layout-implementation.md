# Forms list layout — implementation handover

Implement the redesigned `/forms` index in the live Infosutra app. The Cursor canvas is the **visual spec**. This file is the **execution spec** (decisions, data, files, do-nots). An auto model should follow this document, then match the canvas.

## Visual spec (open beside the work)

[forms-layout-vision-mock.canvas.tsx](/home/sarath/.cursor/projects/home-sarath-work-Infosutra/canvases/forms-layout-vision-mock.canvas.tsx)

Verify against: `http://localhost:5173/forms?study=study-aeeff71f3eb1` (CmF Baseline Study — 9 forms).

## Target

Change **only** the Forms index page unless a tiny shared helper is clearly needed.

- **File:** `Data-Insights-Hub/artifacts/infosutra/src/pages/projects/Projects.tsx` (route `/forms` in `App.tsx`)
- Optional: drop unused `.form-list-row` hover rules in `src/index.css` if the new table no longer uses those classes
- **Do not** change Dashboard, Studies, DQA dashboard, or APIs

## What the page should look like

### Header (quiet)

- Title: **Forms**
- Subtitle when a study is selected: `{n} instruments · {total} submissions` and, if any, `· {red} red flags` (totals from the scoped list + DQA join)
- **Do not** repeat “CmF Baseline Study — Kobo forms in this study (sync, then assign tool codes)”
- **Help** stays outline/ghost; **Sync from Kobo** is secondary (`variant="outline"` or similar), not the hero primary

### Toolbar

- Search (name, tool code, UID) — keep existing filter fields
- Scope chips: **This study (n)** / **Unassigned (n)** — hide **Unassigned** when count is 0
- Sort chips: **Tool code** | **Submissions** | **DQA** | **Last in**
  - Default sort: tool code (T1…T8, missing codes last), then submissions desc
  - DQA sort: `redFlags` desc, then `amberFlags` desc
  - Last in: `lastSubmissionAt` desc (nulls last)
- Column headers that sort (Subs, Last, Red) should stay in sync with the chips
- **Do not** add a Jump/T1–T8 filter row
- **Do not** add page banners for “70 red flags” or “1 form has no tool code”

### Table (full width)

Use a real `<table>` with `table-layout: fixed` (CSS grid + `<p>` cells failed alignment in the mock).

| Column | Source | Notes |
|---|---|---|
| Tool | `project.toolCode` | Mono chip. Missing code: muted “—” plus row hint “Needs a tool code” |
| Form | `project.name` | Grows. No Deployed badge. No sector/country. No per-row sync date |
| Subs | `submissionCount` | Center-aligned. Number only — **no progress bar** (there is no expected count) |
| Last | `lastSubmissionAt` | Relative: Today / Yesterday / `{n}d ago`. This is last **incoming submission**, not `lastSyncAt` |
| Red | `ProjectDqaStat.redFlags` | Flag **counts** (dashboard “alerts”), not red submission counts. `0` → em dash, muted |
| Amber | `ProjectDqaStat.amberFlags` | Same. `0` → em dash |
| Enumerators | `enumeratorCount` | Center-aligned. Label **Enumerators** (not Staff, not Questions) |
| Actions | — | Default: `→`. Hover: `Open · DQA` |

Alignment: Tool + Form **left**; Subs, Last, Red, Amber, Enumerators, actions **center**. Same alignment on headers and cells.

Row chrome:

- Whole row is a link to `/forms/{id}` (preserve `?study=`)
- Hover: wash + inset 3px left bar (CSS `:hover` / `:focus-visible` only — **no** React `onMouseEnter` state). Title can tint to primary
- T1-style exception: if `redFlags > 0`, inset bar can use destructive/red; if no tool code, quieter stroke
- Optional one-line under name: if red flags, `{redSubmissions} of {total} submissions flagged` when those fields exist on `ProjectDqaStat` (`redSubmissions`, `totalSubmissions`); if no tool code, “Needs a tool code”
- Hover **Open · DQA**: both the same accent color on every row (do **not** paint DQA red when the form has flags). `Open` goes to form detail. `DQA` goes to `/dqa?projectId={id}` and must `stopPropagation` so it does not also open the form

Footer: `{n} instruments · {subs} submissions · {red} red · {amber} amber` for the current scope. Study-level last sync can stay in the app chrome/sidebar; do not repeat identical “Synced 13 Sept” on every row.

## Data

```ts
const projectsQuery = useGetProjects();
const dqaQuery = useGetDqaByProject(
  { studyId: activeStudyId ?? undefined },
  { query: { enabled: Boolean(activeStudyId) } },
);
```

Join DQA by `project.id === row.projectId`. Missing DQA row → `redFlags: 0`, `amberFlags: 0`.

`ProjectOut` already has `lastSubmissionAt`, `toolCode`, `enumeratorCount`, `submissionCount`.

Do not invent coverage targets or volume bars.

## Explicitly cut (regression if you put these back)

- Deployed / draft badges on every row
- Sector · country on every row
- Per-row “Synced {date}”
- Questions column
- Relative volume / progress bars next to submissions
- JS hover state duplicated with CSS
- Setup subtitle “sync, then assign tool codes” when the study already has forms
- Unassigned (0) chip
- Callout banners above the table
- Jump T1–T8 filter
- Coloring the hover **DQA** action red on flagged rows

## Empty / error / loading

Keep existing empty cards and Kobo error + Settings link. After sync, keep the existing success/partial banner if `syncData` is set (that is post-action feedback, not a standing callout).

## Verify

1. `/forms?study=study-aeeff71f3eb1` — 9 rows; T1 shows **70** red; others Red/Amber are dashes; English Assessment has no tool code
2. Hover several rows — Open · DQA same color; DQA opens Data Quality for that project
3. Sort chips: Tool / Subs / DQA / Last in
4. Unassigned scope still works when there are unassigned forms
5. Desktop + a narrower width: table still readable, no empty band in the middle of the card

## Out of scope

- Sparklines, keyboard j/k, inline tool-code edit, coverage targets
- Backend or OpenAPI changes
- Rewriting other pages that list forms
