# DQA Phase 0 — Extension Points for Phase 2

Phase 0 refactors the deterministic evaluator so intra-form rules can express
field-to-field comparisons and duration bands without implementing inter-form
functionality. This document records the hooks Phase 2 will build on.

## Phase 0 deliverables (implemented)

| Capability | Rule shape | Notes |
|------------|------------|-------|
| Field vs constant compare | `{ "op": "gt", "field": "C1", "value": 10 }` | Unchanged |
| Field vs field compare | `{ "op": "gt", "field": "B22", "field_b": "B21" }` | Also `lt`, `gte`, `lte`, `equals`, `not_equals` |
| Duration min | `{ "op": "duration_minutes_gte", "start_field": "B2", "end_field": "B3", "min": 20 }` | Unchanged when only min/threshold set |
| Duration max | Same op with `"max": 180` or `"max_threshold": "..."` | Optional upper bound |
| Duration band | Same op with both `min` and `max` | CMF B2–B3 style |

Storage remains **one rule pack per project** (`rule_packs.project_id`). No database migration.

## Evaluation flow (Phase 0)

```text
Rule (JSON check tree)
  → EvaluationContext(data, pack, current, project_rows)
  → resolve_field_value(ref)   ← current submission only
  → eval op handler
  → (passes, details)
  → DqaFlag (unchanged model)
```

## Extension point 1 — EvaluationContext.related

**File:** `app/domain/dqa/context.py`

Phase 0 context holds the current submission's `data`, `pack`, optional `current`
submission row, and `project_rows` for same-project ops (`unique_in_project`,
`group_count_lte`).

Phase 2 will add a documented slot for relationship-resolved submissions, e.g.:

```python
# Phase 2 (not populated in Phase 0):
# related: dict[str, Submission]  # {"register": sub_a, "worker": sub_b}
# related_packs: dict[str, dict]  # pack JSON per role
```

The evaluator must consume resolved context; it must not perform cross-form joins.

## Extension point 2 — Scoped value references

**File:** `app/domain/dqa/refs.py`

Phase 0 `resolve_field_value(ctx, field_ref)` resolves pack aliases against
`ctx.data` only (intra-form).

Phase 2 will extend operand resolution to accept scoped refs:

```text
current.B22     → ctx.data + ctx.pack        (Phase 0: bare "B22" alias)
register.A10    → ctx.related["register"] + register_pack
worker.D4       → ctx.related["worker"] + worker_pack
```

Phase 0 must **not** parse dotted role prefixes or load alternate packs. Unknown
scopes belong in Phase 2 resolver + validator.

## Extension point 3 — Relationship resolution (new service)

**Inspect:** `app/services/triangulation.py` — `_group_by_join()`, `_pick_submission()`

Triangulation views are **analysis UI**, not DQA rules. Phase 2 should extract
shared join/matching utilities rather than importing triangulation view models
into `eval.py`.

Future flow:

```text
Study relationship config (TBD storage)
  → RelationshipResolver
  → populate EvaluationContext.related
  → same compare / equals helpers as Phase 0
```

Example relationship (CMF):

```text
Register.centre_id = Worker.centre_id
  → pair submissions
  → compare register.A10 vs worker.D4
```

## Extension point 4 — Rule ownership (product decision pending)

Inter-form rules may eventually live in:

1. Primary form's rule pack with cross-form refs in the check tree
2. A study-level rule store
3. Both forms' packs (discouraged — duplication)

Phase 0 keeps **project-scoped** `rule_packs` unchanged. Do not migrate to
study-level storage without an explicit product decision.

## Extension point 5 — Recompute orchestration

**File:** `app/services/dqa_evaluation.py` — `evaluate_project(project_id)`

Phase 0 recompute remains per project. Phase 2 inter-form rules require a
study-level orchestrator that:

1. Resolves relationships for the study
2. Evaluates intra-form rules per project (unchanged)
3. Evaluates inter-form rules against paired context
4. Re-runs affected projects when either side of a pair changes

## Extension point 6 — Flags / findings

**Model:** `DqaFlag` — `submission_id`, `rule_id`, `details` JSON

Phase 0 flags remain attached to the **primary** submission. Existing
`details.relatedSubmissions` (from `unique_in_project` / `group_count_lte`) is
the pattern for Phase 2 cross-form diagnostics:

```json
{
  "primarySubmissionId": "...",
  "relatedSubmissions": [{ "submissionId": "...", "projectName": "..." }],
  "left": { "scope": "register", "field": "A10", "value": 12 },
  "right": { "scope": "worker", "field": "D4", "value": 10 }
}
```

No schema migration in Phase 0; document shape only.

## Extension point 7 — LLM compiler target schema

Phase 1 compiler should emit Phase 0 shapes:

- `field_b` for field-to-field comparisons (not a separate `compare_fields` op)
- `duration_minutes_gte` with optional `max` (not a separate `duration_between` op)
- Inter-form scoped refs only after Phase 2 resolver exists

Validator (Phase 1) rejects `field_b` + `value` together on the same check.

## Explicitly out of Phase 0 scope

- `cross_form_compare` operator
- Relationship DB / study-level rule storage
- Cross-form recompute
- Pairwise preview API
- Triangulation ↔ DQA coupling in the eval path
