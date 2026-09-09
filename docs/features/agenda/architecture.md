# Agenda Architecture

## Component diagram

```
  sheet_service · scan_service · pipeline · adaptive_service · feedback_service
        │
        │  event_service.record(db, school_id=…, kind=…, subject=…, subject_id=…,
        │                       summary="Fractions — 7B", detail={"items": 12})
        │       ┌─────────────────────────────────────────────┐
        │       │ never raises   → a log failure cannot roll   │
        │       │ never commits  → it joins the caller's txn   │
        │       └─────────────────────────────────────────────┘
        ▼
  Event(id, school_id, kind, occurred_at, actor, subject_type, subject_id,
        summary NOT NULL ≤200, detail JSON)
        │        subject_id: NOT a foreign key                      (I-agenda-02)
        │        occurred_at: separate from created_at — a pile corrected on
        │                     Sunday carries Friday's lesson date
        ▼
  GET /timeline?kind=&q=&from=&to=&cursor=
        │
        ├─ conditions = [ … ]        ONE list, built once
        ├─ page   = select(Event).where(*conditions).order_by(occurred_at desc)
        ├─ total  = count(*)         .where(*conditions)      ← same list
        ├─ facets = group_by(kind)   .where(*conditions)      ← same list  (I-agenda-05)
        │
        └─ _titles(events)           three batched queries over Sheet / Scan / Source
                                     missing subject → resolved:false     (I-agenda-06)

  ── one-off ──
  cli: backfill-events → services/event_backfill.py
        Source.created_at            → SOURCE_IMPORTED
        SourceSection.extracted_at   → CHAPTER_READ
        Sheet.created_at             → SHEET_CREATED
        Sheet.rendered_at            → SHEET_RENDERED
        Scan.created_at              → SCAN_UPLOADED
        max(Attempt.answered_at)/sheet → SCAN_CONFIRMED
        ── and nothing else ──                                  (I-agenda-07)
```

## Data flow

### Why `occurred_at` is not `created_at`

A pile corrected on Sunday evening carries **Friday's** lesson date. The row was created
on Sunday; the thing it describes happened on Friday. An agenda ordered by row-creation
time would put the term in the wrong order for exactly the teachers who correct in
batches — which is most of them.

### Why `subject_id` is not a foreign key

Two independent reasons:

1. **The log must outlive what it describes.** Deleting a sheet does not un-print it.
2. **One column cannot point at four tables** (`Sheet`, `Scan`, `Source`, `Class`).

The consequence is that titles are resolved at read time and fall back to the stored
`summary` — which is why `summary` is `NOT NULL`, and why it may never hold a student
name (I-agenda-03).

### The read path — facets that cannot lie

The endpoint follows the shape of the exercise listing in `sources.py`: **one** list of
filter conditions, built once and applied identically to the page, the count and the
facets. A chip can therefore never promise a different set than selecting it returns.

Title resolution is batched — three queries for a page of twenty events, not twenty
round trips for a screen a teacher opens daily.

## Component interaction

### `record` — one writer, three properties

```python
def record(db, *, school_id, kind, subject, subject_id, summary, detail=None) -> Event | None
```

- **The only writer.** Nothing else inserts an `Event`.
- **Never raises.** It logs a warning and returns `None`.
- **Never commits.** It joins the caller's transaction, so an event and the work it
  describes land together or not at all.

Those three together are what make it safe to call from inside a service doing real
work. An agenda missing one line is a small loss; a confirmed scan lost because its log
row would not write is a class's evening of marking.

### The backfill — evidence only

What **can** honestly be reconstructed is listed in the diagram above. What cannot, and
is therefore not invented:

> **A sheet being printed.** Nothing ever recorded it — that absence is half the reason
> the log exists — so no `SHEET_PRINTED` is manufactured. Deriving one from
> `rendered_at` would put a fact in the log that nobody observed, and an agenda that
> quietly guesses is worse than one with a gap: the teacher cannot tell which lines are
> evidence and which are inference.

Confirmation is the one *derived* event, and it is honest: it uses the attempts' own
`answered_at`, the same stamp `confirm_scan` writes, so the reconstructed line lands on
the day the class actually sat the sheet.

Idempotent by construction: every event carries the subject it describes, so a second
run finds the `(kind, subject_id)` pair already present and adds nothing.

### Lineage

`Sheet.derived_from_id` points a differentiated sheet at the **common** sheet whose
results justify it. That is what makes the two one teaching unit rather than two rows
with adjacent dates, and it is the edge a future unit view walks.

## Edge cases

- **The log row cannot be written.** → warning, `None`, and the real work proceeds.
- **A summary longer than 200 characters.** → truncated, never refused. It is a fallback
  title, not data.
- **The subject was deleted.** → the line still shows, `resolved: false`, rendered
  without a link.
- **A `CHAPTER_READ` event.** → resolves against the `SourceSection` it names, not the
  `Source`.
- **A colleague's class.** → filtered out by `owned_class_ids`.
- **The backfill run twice.** → the second run adds nothing.
- **A brand-new database.** → the backfill writes nothing, honestly.

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
