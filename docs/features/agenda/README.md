# Agenda

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers

---

## 1 · What it does

A teacher's question about a term is chronological: *what did I do with 7B in March, and
which of it still needs correcting?* Nothing in the schema could answer it. Rows carry
`created_at` and `updated_at`; the second is overwritten by whatever edit came last, so
it cannot say when a pile was **confirmed** — and the two moments that matter most to a
chronology (a sheet going to the photocopier, a scan being confirmed) left no trace at
all.

So `event` is an **append-only log** with its own `occurred_at`, and `/timeline` is the
one ordered query across every verb the product knows.

```
  every service that does something worth remembering
        │   event_service.record(kind, subject, summary, detail)
        │   never raises · never commits
        ▼
  Event(kind, occurred_at, actor, subject_type, subject_id, summary, detail)
        │        subject_id is NOT a foreign key — the log outlives what it describes
        ▼
  GET /timeline?kind=&q=&from=&to=
        │  one list of filter conditions, applied identically to the page,
        │  the count and the facets
        ▼
  titles resolved AT READ TIME against the rows the events point at
        │  deleted subject → still shown, resolved:false, rendered without a link
        ▼
  the agenda: newest first, grouped by day, faceted, searchable
```

`python -m alppy.cli backfill-events` reconstructs the agenda for work that happened
before the log existed — **only from evidence**.

### Key properties

1. **The log is subordinate to the work.** A failure to log must never roll back the
   thing being logged.
2. **It stores no PII.** `summary` is what the agenda shows when the row it describes
   has been deleted: a sheet title, a filename, a chapter — never a student name.
3. **It never guesses.** The backfill reconstructs what a real timestamp recorded, and
   nothing else.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-agenda-01 | `event_service.record` **never raises and never commits.** | `services/event_service.py::record` | A confirmed scan must not be lost because its log row would not write | A class's evening of marking lost to a logging bug |
| I-agenda-02 | `Event.subject_id` is **deliberately not a foreign key.** | the model | The log must outlive what it describes — deleting a sheet does not un-print it — and one column cannot point at four tables | History erased by a cascade |
| I-agenda-03 | **`summary` never holds a student name**, and `detail` holds counts, never free text. | `services/event_service.py` (contract), review | The log is read back by a teacher and, one day, exported | PII in a table nobody thinks of as PII |
| I-agenda-04 | `summary` is **NOT NULL** and truncated at `MAX_SUMMARY` (200), never refused. | `record` | It is the fallback title for a deleted subject | An agenda line with nothing to show |
| I-agenda-05 | The **facets promise exactly what selecting them returns**: one list of conditions, applied to the page, the count and the facets alike. | `api/v1/timeline.py` | A chip that lies is worse than no chip | "12 scans" that filters to 3 |
| I-agenda-06 | An event whose subject was **deleted still shows**, marked `resolved: false`, and is rendered without a link. | `api/v1/timeline.py::_titles` | Deleting a sheet does not un-print it | A 404 from a history page |
| I-agenda-07 | The **backfill invents nothing.** No `SHEET_PRINTED` is manufactured; it is idempotent by `(kind, subject_id)`. | `services/event_backfill.py` | An agenda that quietly guesses is worse than one with a gap | The teacher cannot tell evidence from inference |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/services/event_service.py` | `record` (the **only** writer), `list_events`, `MAX_SUMMARY` | `models` |
| `alppy/services/event_backfill.py` | Reconstruction from existing timestamps, idempotent | `models` |
| `alppy/api/v1/timeline.py` | `GET /timeline`, the facets, batched title resolution | `event_service`, `class_service` |
| `alppy/cli.py` | `backfill-events` | `event_backfill` |
| `EventKind` / `EventSubject` (enums) | The verbs and the four subject tables | — |
| `apps/web/src/app/[locale]/timeline/` | The agenda screen: grouped by day, faceted, searchable | `packages/shared` |
| `Sheet.derived_from_id` | The lineage edge: the common sheet a differentiated one answers | — |

**The verbs:** `source_imported` · `chapter_read` · `sheet_created` · `sheet_rendered` ·
`sheet_printed` · `scan_uploaded` · `scan_confirmed` · `adaptive_proposed` ·
`adaptive_exported` · `feedback_written` · `feedback_approved`.

---

## 4 · How to extend this feature

**Adding a verb.** Add to `EventKind`, call `record` from the service that performs the
action — *inside* the same transaction, since `record` does not commit — and add the
title resolution if it points at a new subject type. Do not add a column to the subject
table: that is the design D36 rejected.

**Adding a filter.** It goes in the single condition list, so the page, the count and
the facets cannot disagree (I-agenda-05).

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does `record` now raise, or commit? (I-agenda-01 — never)
- [ ] Did `subject_id` become a foreign key? (I-agenda-02 — never)
- [ ] Could a student name reach `summary` or `detail`? (I-agenda-03 — never)
- [ ] Does a new filter apply to the facets and the count as well as the page? (I-agenda-05)
- [ ] Does the backfill now derive an event nobody observed? (I-agenda-07 — never)

---

## 5 · Privacy & safety

| Data | Where it is stopped | Why |
|---|---|---|
| Student name | Never in `summary` or `detail`, by construction | The log is long-lived and exportable; keeping PII out by construction is cheaper than scrubbing it later |
| Free text | `detail` holds counts only | Same reason |
| A colleague's class | `owned_class_ids` scopes the query | A teacher's agenda is theirs |

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-agenda-01 | `test_timeline.py::test_a_failing_record_returns_none_instead_of_raising` |
| I-agenda-02 | `test_timeline.py::test_a_deleted_subject_still_shows_but_is_not_linkable` |
| I-agenda-03 | review + `test_timeline.py::test_search_matches_the_summary` (what summaries hold) |
| I-agenda-04 | `test_timeline.py::test_the_summary_is_truncated_rather_than_refused` |
| I-agenda-05 | `test_timeline.py::test_a_facet_reports_what_selecting_it_would_give`, `::test_paging_reports_the_full_total`, `::test_a_date_range_bounds_the_agenda` |
| I-agenda-06 | `test_timeline.py::test_a_deleted_subject_still_shows_but_is_not_linkable`, `::test_a_chapter_event_resolves_against_the_section_it_names` |
| I-agenda-07 | `test_event_backfill.py::test_the_backfill_never_invents_a_print`, `::test_the_backfill_reconstructs_history_and_repeats_harmlessly` |
| Tenancy | `test_timeline.py::test_a_colleague_never_sees_another_teachers_class_events` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_timeline.py \
  apps/api/tests/test_event_backfill.py -q
```

---

## Companion documents

- [`architecture.md`](architecture.md) — the log, the read path, the backfill
- [`decisions.md`](decisions.md) — D36, D38
- [`../platform/`](../platform/) — jobs, tenancy, the error envelope

**Last updated:** 2026-09-09
