# Agenda Decisions Log

D-numbers follow the repo-wide [`docs/decisions-log.md`](../../decisions-log.md).

---

## D36 · The agenda is an append-only log, not a column per lifecycle moment

**Date:** 2026-09 · **Affected invariants:** I-agenda-01, I-agenda-02, I-agenda-04

**Background.** Every row already carried `created_at` and `updated_at`, and neither
could answer what a teacher asks of a term. `updated_at` is overwritten by whatever edit
came last, so it can never say when a pile was *confirmed*. And the two moments that
matter most to a chronology left no trace anywhere: **a sheet going to the photocopier**
(`rendered_at` is when the PDF was built, often days earlier) and **a scan being
confirmed** (a status enum flip, nothing more).

**Considered alternatives**
- A) *A column per moment* (`printed_at`, `confirmed_at`, …). Rejected: a migration every
  time the product learns a new verb, and still no single ordered query across all of
  them.
- B) *Derive the chronology at read time from existing timestamps.* Rejected: it cannot
  express what was never recorded, which is the half that matters.
- C) **An append-only `event` log with its own `occurred_at`.** Chosen.

**Tradeoff**
- ✅ One ordered, faceted, searchable query across every verb
- ✅ New verbs cost an enum value, not a migration on a hot table
- ✅ `occurred_at` separate from `created_at`: a pile corrected on Sunday carries
  Friday's lesson date
- ❌ Titles must be resolved at read time
- ❌ A second place that has to be kept free of PII

**Two design points inside it:**

- **`Event.subject_id` is deliberately not a foreign key.** The log has to outlive what
  it describes — deleting a sheet does not un-print it — and one column cannot point at
  four tables. Titles fall back to the stored `summary`, which is why `summary` is
  `NOT NULL` and may never hold a student name.
- **`record` never raises and never commits.** An agenda line is worth less than the work
  it describes: a confirmed scan must not be lost because its log row would not write.

**`Sheet.derived_from_id` was added in the same pass.** It is what makes a common sheet
and the differentiated sheets its results justify one teaching unit rather than two rows
with adjacent dates.

---

## D38 · The agenda is backfilled from evidence, and only from evidence

**Date:** 2026-09 · **Affected invariant:** I-agenda-07

**Background.** Without a backfill, `/timeline` on an existing database is an empty
screen saying nothing happened until the day the feature shipped — which is untrue, and
exactly the impression that makes a teacher stop opening it.

**What can honestly be reconstructed**

| Evidence | Event |
|---|---|
| `Source.created_at` | a textbook was imported |
| `SourceSection.extracted_at` | a chapter was read |
| `Sheet.created_at` | a sheet was built |
| `Sheet.rendered_at` | its PDFs were produced |
| `Scan.created_at` | copies were uploaded |
| newest `Attempt.answered_at` per scanned sheet | the pile was confirmed |

**What cannot, and is therefore not invented: a sheet being printed.** Nothing ever
recorded it — that absence is half the reason the log exists. Deriving `SHEET_PRINTED`
from `rendered_at` would put a fact in the log that nobody observed, and an agenda that
quietly guesses is worse than one with a gap: the teacher cannot tell which lines are
evidence and which are inference.

Confirmation is the one derived event, and it is honest — it uses the attempts' own
`answered_at`, the same stamp `confirm_scan` writes, so the reconstructed line lands on
the day the class actually sat the sheet.

**Idempotent by construction:** every event carries the subject it describes, so a
second run finds the `(kind, subject_id)` pair already present and adds nothing.

---

## Facets are built from the same conditions as the page

**Date:** 2026-09 · **Affected invariant:** I-agenda-05

`api/v1/timeline.py` follows the shape of the exercise listing in `sources.py`: one list
of filter conditions, built once, applied identically to the page, the count and the
facets. A chip that says "12 scans" and then filters to three is worse than no chip at
all — it makes the teacher distrust the screen rather than the number.

---

## When policy changes

```json
{
  "change": "make Event.subject_id a foreign key with ON DELETE CASCADE",
  "reason": "orphan rows are untidy",
  "date": "YYYY-MM-DD",
  "decision": "rejected — violates I-agenda-02",
  "rationale": "the orphan rows ARE the feature. Deleting a sheet does not un-print it,
                and the log is the only record that it was."
}
```
