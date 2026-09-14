# Fix-3 — interactive template authoring (user as judge)

**Status:** implemented.

**Builds on:** binder (map words to allowed names; do not invent SQL).
Fix-2’s nickname registry is still parked.

## Product

Creating or editing a template **is** a chat session on `/report-templates`.
Compose (`/report-composer`) is removed.

- **New template** opens a draft (no published version) and a welcome message.
- Each turn streams planner / binder / clash-check steps as collapsible progress.
- The user is the judge: the LLM “faithful?” call is skipped on this path.
- Shared `fieldKey`s without `toolCode` pause and ask which form.
- Nickname remaps (e.g. interviewer → enumerator) are applied only onto catalog
  names, then confirmed in the thread.
- **Save version** publishes the working spec. Preview executes that spec.

## Pipeline

```text
You write / reply
        ↓
   Planner (LLM, no judge) → draft spec
        ↓
   Compiler + validator
        ↓
   Binder (LLM) → allowlisted name maps only
        ↓
   Conflict check (no LLM) → same fieldKey on two tools, no toolCode?
        ↓
   Need a human?  ──yes──► pause, ask in the chat
        ↓ no
   Show spec + “is this what you meant?”
        ↓
   Confirm or refine  → Save as template version
```

Catalog `studyFieldKeys` are `{ fieldKey, label, toolCode, toolLabel }` and are
**not** collapsed across tools.
