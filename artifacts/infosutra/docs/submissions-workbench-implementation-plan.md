# Submissions workbench — implementation plan

Hand this file to Auto. Implement the **approved UI mock**, not a redesign of the mock.

- Live page: `/forms/:id/submissions?study=…`
- Mock (visual source of truth): `~/.cursor/projects/home-sarath-work-Infosutra/canvases/submissions-workbench-mock.canvas.tsx`
- Prior review (why, not what): `~/.cursor/projects/home-sarath-work-Infosutra/canvases/submissions-grid-ui-review.canvas.tsx`

This page is a **DQA review workbench**. Full spreadsheet is a secondary mode. Do not rebuild the project-details submission list inside the sticky column.

---

## Success criteria

On `Register, Observation and AWW Interview (Anganwadi)` (`aDwASYubvG8bqPCoZrXGZJ`, study `study-aeeff71f3eb1`):

1. Default view is **Review**: identity columns + flagged questions only. Instrument fields (`today`, `deviceid`, `username`, and similar) are hidden.
2. Header is **breadcrumb + “Form data”**, not the truncated 80-character instrument name. “Project details” stays.
3. Quality filters are **segments** (All / Flagged / Red / Amber / Clean), not an unlabeled `<select>`.
4. Sticky identity is **enumerator · centre · submitted time** with a small severity pip. Kobo ID is secondary (hover/title or a small mono line), not the lead.
5. Flagged cells show **value + severity color only**. No rule hashes (`R-111d29f595d8`) in the cell.
6. Clicking a flagged cell opens the sheet with: recorded answer, **related answers for the same rule**, human rule title + message, open-full-form link.
7. The table is the **only vertical scroller** in the main pane (fills remaining viewport under sticky chrome). No nested page-scroll + `max-h-[70vh]` combo.
8. Row height is **uniform** (one-line identity; no stacked RED/AMBER badge tower).
9. Verify in the browser at desktop width on the live form above. Exercise filters, Review/All, a flagged cell sheet, pagination, and CSV.

---

## Out of scope (do not do)

- Column virtualization / windowing
- Server-side “export all matching rows”
- Keyboard next/previous-flag tour
- New Data Explorer / Project details consolidation
- Changing DQA rule engine or flag computation
- Regenerating the Orval client unless you add API fields (prefer frontend-only if possible)
- Visual restyle of the app sidebar

---

## Files to change

Primary (expect most of the work here):

- `Data-Insights-Hub/artifacts/infosutra/src/pages/projects/ProjectSubmissions.tsx`
- `Data-Insights-Hub/artifacts/infosutra/src/pages/projects/SubmissionsGrid.tsx`

Likely small edits:

- `Data-Insights-Hub/artifacts/infosutra/src/components/layout/Header.tsx` — only if breadcrumb/title cannot be expressed via existing `title` / `description` / `action` without making Header worse for other pages. Prefer composing breadcrumb **inside** `ProjectSubmissions` (custom header block) rather than overloading the global Header for every screen.

Optional API (only if frontend cannot derive groups cleanly):

- `Data-Insights-Hub/artifacts/api-python/app/services/submission_grid.py` — while walking `survey`, track `begin_group` / `end_group` and set `group` / `groupLabel` on each column
- `Data-Insights-Hub/artifacts/api-python/app/schemas/submissions.py` — add optional `group`, `groupLabel` on `GridColumn`
- Generated TS types in `Data-Insights-Hub/lib/api-client-react/src/generated/api.schemas.ts` **or** a local frontend type overlay — do not leave the UI compiling against missing fields

Existing API already has what Review mode needs: `column.flagged`, `column.filled`, `column.type`, `row.enumerator`, `row.submittedAt`, `row.location`, `row.koboId`, `row.redFlags`, `row.amberFlags`, `row.cells[key].flags[]` with `title` / `message` / `ruleId` / `severity`.

---

## Behavior spec (match the mock)

### 1. Page chrome — `ProjectSubmissions.tsx`

Replace the current Header copy:

- Title area:
  - Line 1 (muted, small): `{studyName} / {shortFormName}`
  - Line 2 (semibold): `Form data`
- `shortFormName`: first clause of `project.name` or a truncated name with full name in `title` tooltip. Do **not** append `" data"` to the long name.
- Drop the subtitle “All forms in one table — coloured cells carry DQA flags”.
- Keep a control that links to `/forms/${projectId}` labeled **Project details**.
- Study name: `useStudy()` active study (same pattern as the sidebar).

Main pane:

- `flex-1 min-h-0 overflow-hidden` (not `overflow-auto` + padding that creates a second scroller).
- Pass `project` into the grid if useful for name/centre field detection; otherwise keep `projectId` only.

### 2. Toolbar — `SubmissionsGrid.tsx`

Two rows, sticky above the grid, not a wrapping junk drawer.

**Row 1 — quality + who + mode + export**

- Segments (buttons or existing `ToggleGroup` if the design system has one): `All` · `Flagged` · `Red` · `Amber` · `Clean`
  - Wire to existing `severity` query param (`""` | `flagged` | `red` | `amber` | `clean`). Reset page to 1 on change.
  - Labels can include **current result total** from `grid.total` (that total is already filter-aware). Do not invent “41 red” as a global if the API only returns the filtered total. Copy like `All · 61` when unfiltered, `Flagged · 41` when that filter is on.
- Enumerator search: keep debounce; placeholder `Enumerator…`.
- Mode toggle: **Review** | **All questions** (see column rules below).
- Export: keep page CSV; button label `Export` or `Export page`. Tooltip must say it is the current page only.

**Row 2 — sections + helper text**

- Chips: `Flagged questions` | groups derived from the form (e.g. `A Registers`, `B Observation`).
- Helper text:
  - Review: `N questions in review · instrument fields hidden`
  - All: `Showing all questions · M more off-screen` (M = hidden by horizontal overflow is optional; at least state column count).

Remove the old unlabeled `<select>`s for severity. Page size can move into a compact control in the pagination footer (keep 25/50/100/200).

Remove the two raw checkboxes **as the primary UI**. Their logic becomes:

| Old checkbox | New control |
|---|---|
| Flagged questions only | Review mode, or section chip “Flagged questions” |
| Hide empty questions | Always on in Review; still on by default in All questions |

### 3. Column model

Classify columns on the client (no API required for v1):

**Instrument / meta** — hide in Review unless All questions:

- codes/types matching: `today`, `deviceid`, `username`, `start`, `end`, `audit`, `phonenumber`, plus `column.extra === true` meta like GPS/Photos **unless** they are flagged.

**Identity (pin, not in the scrolling question set):**

- Prefer cells: `district`, `block`, `centre_code` (and aliases `DC` is enumerator — do not pin DC if enumerator is already in the sticky column).
- Pin **District** (and Centre if not already in the identity cell). If a field is missing on this form, omit the column — do not show empty stubs.

**Review question set:**

- Default section `flagged`: columns with `flagged > 0`.
- Section chip for a group: columns in that group (still hide instrument fields).
- If a group has no flagged columns and quality is Flagged/Red, still show the group’s visible questions when that chip is selected.

**All questions mode:**

- All non-empty columns (current `hideEmptyColumns` behavior), including instrument fields.
- Horizontal scroll is expected.

**Deriving groups without API (preferred first):**

`useGetProject` already loads the project. Walk `project.formDefinition.survey` (confirm the actual camelCase field on the TS project type). On `begin_group`, remember label/name; on `end_group`, pop; assign that group to following question names. Match to `GridColumn.code` / `key`.

If `formDefinition` is missing on the client type, add `group`/`groupLabel` in `submission_grid._survey_columns` instead of guessing from question prefixes (`A1`, `B2`). Prefix guessing is a fallback only.

### 4. Grid layout

Single card/surface, `flex-1 min-h-0`, inner `overflow-auto`. Sticky:

- Header row `sticky top-0`
- Identity column `sticky left-0` (and District if pinned)

**Identity cell (compact, ~48–56px row):**

```
●  Enumerator name
   {centre_code} · {formatted submittedAt}
```

- `●` pip: red / amber / muted for clean (`row.severity`).
- `title` on the cell: Kobo id + full timestamp + “N red · N amber”.
- Form-level flags (`row.rowFlags`): small text button under the second line **or** treat as opening the sheet with column label “Form-level checks”. Do not add a second badge stack.
- Link to `/submissions/:id` can wrap the enumerator name or sit in the sheet. Do not lead with an underlined Kobo id.

**Pinned District:** plain text, no wrap explosion.

**Flags column:** `2 red` / `1 amber` / `—` as text, not destructive Badge piles.

**Question headers:**

- Primary: question **code** (`A10`)
- Secondary: label, one line, truncate with `title` for full text
- Do not show `code · N flagged` in the header; the Review set already implies flagged.

**Question cells:**

- Format display values: ISO datetimes → same `formatDateTime` as the identity column; times like `08:30:00.000+05:30` → `08:30`. Keep numbers and yes/no as-is.
- Empty: muted `Blank` or `—`.
- Flagged: severity wash **or** left 3px severity bar + light fill (mock uses bar + fill). Clickable. Dotted underline optional; **no rule id line**.
- Clean: value only, not a button.

Pagination footer stays under the scroller (not inside it): page X of Y, Previous/Next, page-size.

### 5. Sheet

Keep the right `Sheet`.

When opening from a cell:

1. Recorded answer (show **Blank** if empty — today’s bug hides the block when `value` is falsy).
2. **Related answers:** other cells on the **same row** whose `flags` share a `ruleId` with the opened cell. Label with column code + formatted value. If the rule mentions a field with no cell value, still list it as Blank if that column exists on the grid.
3. Flag list: severity pip + **title** + message. Keep the “All forms flagged by {ruleId}” link, but do not make the hash the headline.
4. Enumerator · time
5. Open full form `{koboId}`

Form-level sheet: skip “recorded answer”; list `rowFlags`; still show related cells if any rule ids appear on cells.

### 6. Defaults (state)

```ts
severity: "flagged"          // was ""
columnMode: "review"         // flagged questions only
section: "flagged"
hideEmptyColumns: true
limit: 50                    // unchanged
```

Switching to **All questions** sets `columnMode: "all"` and does not have to change `severity`.

Switching quality to `clean` with Review mode: Review columns may be empty (no flagged questions). Empty-state copy: “No flagged questions in this result. Switch to All questions.” Do not dump 158 columns as a surprise.

### 7. Visual / design system

- Reuse existing shadcn `Button`, `Input`, `Badge` (sparingly), `Sheet`.
- Do not introduce a new CSS framework.
- Severity colors: keep current red/amber Tailwind tokens (`bg-red-100`, `bg-amber-100`, dark variants). Mock’s left bar is preferred for cells; pip for row identity.
- No new gradients, shadows, or emoji.

---

## Implementation order (do this sequence)

1. **Layout shell** — `ProjectSubmissions` chrome + single-scroll flex column. Grid still works with old toolbar.
2. **Toolbar** — segments, enumerator, Review/All, export; move page size to footer.
3. **Column rules** — Review default, instrument hide, pin district/centre, section chips from form groups (or API group fields).
4. **Identity + cell chrome** — compact rows, no hashes, value formatting.
5. **Sheet** — always show answer; related cells by shared `ruleId`.
6. **Browser verify** on the Anganwadi URL (desktop). Fix anything that regresses empty/loading/error states.

---

## Tests

- If `artifacts/api-python/tests/test_submissions_dqa.py` (or grid tests) exist and you touch `_survey_columns`, add a case: group metadata on columns from a tiny survey with `begin_group`.
- Frontend: there may be no grid test. Do not add a heavy harness. Manual browser check is required.
- Do not change CSV column order except if you drop hidden columns (CSV should export **visible** columns, same as today).

---

## Suggested commit (when the human asks)

One commit is enough:

`Make the submissions grid a review workbench`

Body: default to flagged questions, compact identity, section/quality chrome, richer flag sheet.

Do **not** commit unless the user asks.

---

## Agent notes

- Work in `Data-Insights-Hub/artifacts/infosutra` (Vite app on port 5173).
- Keep `study=` query behavior; do not break `useFormRouteId` / study provider.
- `placeholderData` on the grid query must stay so filter changes do not flash an empty table.
- If you add API fields, keep them optional so old clients do not break.
- Match the mock’s information architecture even if Tailwind classes differ.
}
