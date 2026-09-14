# Parked: Fix-2 — catalog as a declared map

**Status:** **not required for the current product path.** Nickname mapping is
now part of **fix-3** (binder + user confirms). Keep this note only if we later
need extra first-class ops columns (district, block) without touching the
query engine.

Implement only if the user explicitly says **implement fix-2** for that
remaining piece.

## What fix-3 already covers

“Interviewer” meaning enumerator is a **word problem**. A YAML nickname list is
still a dictionary we maintain. Fix-3’s binder + “is this what you meant?”
handles that without a new catalog file.

Form questions (`child_age`, `A10`) stay on the answers table. Fix-3 also
fixes **same field name on two forms** by listing `fieldKey` + tool and asking
which form.

## What would still be fix-2 (optional, later)

The frozen sets in `catalog.py` (`enumerator`, `toolCode`, `isClean`, …) are
Infosutra’s **ops vocabulary**, wired to SQL columns. That lock should stay.

We would only reopen this if we want to add a new ops breakdown (e.g. district
as a real column on submissions) **without** editing the engine — a declared
map of name → column. Until district (or similar) is ingested as its own
column, an LLM cannot invent it. If district is already a form question, it
works as an answer field under fix-3.

## Out of scope

Inventing SQL. Replacing the allowlist. Percents/medians.

**Discussion:** 2026-09-14, after reading `catalog.py`. Picture:
[Two catalogs in one file](/home/sarath/.cursor/projects/home-sarath-work-Infosutra/canvases/catalog-two-layers.canvas.tsx)
(local canvas; the written plan below is the source of truth).

## The problem in plain language

`catalog.py` holds frozen sets of names (`enumerator`, `toolCode`, `isClean`, …)
and maps each name onto a SQLAlchemy column. That looks like we hardcoded the
product to today’s Infosutra tables.

There are actually two kinds of “columns”:

1. **Operations data (same idea for every study).** Who submitted, which tool,
   which day, whether it was clean, which flags fired. Infosutra chose those
   names and those tables. The frozen list is that vocabulary. The query engine
   only accepts those names so the language model cannot invent SQL.

2. **Form answers (different in every study).** Kobo questions such as
   `child_age` vs `q3_umur`. These are **not** meant to live in `catalog.py`.
   On ingest they go into `submission_answers`. The planner catalog already
   adds this study’s keys as `studyFieldKeys`.

So: different questionnaires already work. Different **words** for the same ops
idea, or extra ops breakdowns (district, block, school as first-class fields),
do **not**.

## Examples that make the split felt

```text
"average child_age"
  → form answer. Works today (entity answer, fieldKey = child_age).

"count by enumerator"
  → Infosutra column. Works today (on the frozen list).

"count by interviewer"
  → same column as enumerator, wrong word. Fails. No nicknames.

"break down by district"
  → works only if district is a question on the form.
     There is no first-class district field unless we add it in code.
```

## What we want later (do not implement until asked)

Keep the **lock** (only allowed names, never raw SQL). Stop storing the **list
of names** as module-level frozen sets wired to ORM classes.

Split them:

- A **resolver** that still refuses unknown names and still compiles to
  parameterized SQL.
- A **declared map** we can grow without rewriting the query engine:
  our name, which entity, which column or projection, labels, optional
  study nicknames (interviewer → enumerator), extra dimensions when we
  ingest them.

Form questions stay the dynamic appendix they already are (`fieldKey`).

## Out of scope for fix-2

Fix-1 (per-item KPI cards). Query grammar (percents, median). Opening the
engine so the model can emit arbitrary SQL.

## Why not “just make it generic SQL”

Safety. The rewrite’s rule is: the model describes a question in our language;
code turns allowed names into SQL. A registry still does that. A free-form
query language would undo it.
