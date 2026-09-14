# Fix-1 — per-item KPI queries

**Status:** implemented (2026-09-14). Do not re-implement unless regressing.

**Problem:** `kpi_group` was one Query IR bound to many labels. Glance rows like
“submissions today, cumulative, open RED, open AMBER” need **four questions**
(different entities and windows) but one visual row.

## Contract (shipped)

`kpi_group` items may each own a query. Component-level query remains valid for
same-window legacy groups (`label` + `field`).

Execute result shape: `{ "items": [{ "label", "value", "error?" }] }`.

See also: planner/repair prompts (`ONE QUERY PER CARD`), `compile.py`,
`validation.py`, `execute.py`, preview/PDF renderers.