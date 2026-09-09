# Feature Documentation

Every subsystem of Alppy, documented as the framework in [`FRAMEWORK.md`](FRAMEWORK.md)
prescribes: **what it does**, the **invariants** that are load-bearing, and **why**
each one exists. The invariants are the point. They are the rules a reviewer — or an
LLM — has to enforce by reading, because no linter can see them.

**Status:** describes `main` as of 2026-09-09.

---

## The thirteen features

The product is a loop: a teacher imports a book, builds a sheet, prints it, scans
the copies back, gets grades, gets a mastery matrix, and generates the next,
differentiated sheet from it. Nine of these features are stages of that loop; three
(`platform`, `ai`, `design-system`) are the ground it stands on.

```
       ┌──────────────────────────── the loop ─────────────────────────────┐
       │                                                                   │
  corpus ──▶ retrieval ──▶ sheets ──▶ [ paper, photocopier, classroom ]    │
  (a book)   (ranking)     (A4 PDF)              │                         │
       ▲                                    scanning                       │
       │                                    (registration, UID, marks)     │
       │                                         │                         │
       │                                     grading                       │
       │                                    (verdicts → attempts)          │
       │                                         │                         │
       │                                     mastery                       │
       │                                    (five bands)                   │
       │                                         │                         │
       └──── adaptive ◀── feedback ◀─────────────┘                         │
             (next sheet)  (why it was wrong)                              │
                                                                           │
  agenda ── records every one of those moments, append-only ───────────────┘

  platform · ai · design-system  — underneath all of it
```

| Feature | What it is | Invariants |
|---|---|---|
| [`platform/`](platform/) | Auth, tenancy, jobs and the worker, object storage, error envelope, rate limit | `I-platform-01..08` |
| [`corpus/`](corpus/) | PDF ingestion: extract, chunk, embed, sections, exercise regions cut as images | `I-corpus-01..09` |
| [`retrieval/`](retrieval/) | Ranking textbook exercises for a sheet, with provenance | `I-retrieval-01..07` |
| [`sheets/`](sheets/) | The builder, the print geometry, the two PDFs | `I-sheets-01..10` |
| [`scanning/`](scanning/) | Registration, UID decode, bubble detection, answer-box crops | `I-scanning-01..10` |
| [`grading/`](grading/) | Graders, the teacher's barème, the vision grader, confirmation | `I-grading-01..10` |
| [`mastery/`](mastery/) | accuracy × recency, five bands, snapshots, the matrix | `I-mastery-01..08` |
| [`results/`](results/) | Points per pupil and per sheet, item-confidence diagnostics, the `/results` dashboard | `I-results-01..04` |
| [`adaptive/`](adaptive/) | Gap targeting, generation, approval, N groups from one sheet | `I-adaptive-01..10` |
| [`feedback/`](feedback/) | Per-student misconception notes, as their own document | `I-feedback-01..07` |
| [`ai/`](ai/) | Provider-agnostic model layer, the PII gate, grounding, the audit log | `I-ai-01..08` |
| [`agenda/`](agenda/) | The append-only event log and `/timeline` | `I-agenda-01..07` |
| [`design-system/`](design-system/) | Tokens, recipes, brand assets, the rules lint cannot catch | `I-design-01..10` |

---

## The three-document rule

Each folder holds exactly three documents, and none of them is optional:

| Document | Answers | Read it when |
|---|---|---|
| `README.md` | *What does this do, and what must never break?* | You are about to change this subsystem |
| `architecture.md` | *How do the pieces talk, and what are the edge cases?* | You are changing the design, not just the code |
| `decisions.md` | *Why is it like this?* | You want to change a rule, not obey it |

---

## How to read an invariant

Each one names where it is enforced, and — this is the part that matters — a real
test that fails if it is broken. Alppy's test names are sentences on purpose:

```
I-grading-04  A missing verdict is never a zero.
              Enforced in  scan/open_grading.py::grade_open_vision
              Proved by    tests/test_open_grading.py::test_no_verdict_is_not_a_zero
```

Run everything an invariant table cites:

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q
```

There is no `tests/**/test_invariants.py` in this repo, and there deliberately is
not one: the invariants are proved by the suite that already exists, named after
the behaviour rather than the rule. Each README §6 lists the exact tests.

---

## Extending a feature

1. Read `README.md` §2 of the feature you are touching. It is a contract, not advice.
2. List, in the PR description, which `I-*` your change touches.
3. Make sure a test covers each one. If your change makes an existing test's name a
   lie, that is the signal — the rule moved, and it needs a decision entry.
4. If you introduce a rule, add it to §2 **first**, then to `decisions.md` with a
   D-number, then to [`docs/decisions-log.md`](../decisions-log.md).

### Cross-feature rules

Some invariants are held jointly, and are the easiest ones to break from the
outside:

- **Geometry** — `I-sheets-03` (a layout number is a version bump) is enforced by
  `scanning` refusing a page printed under another version (`I-scanning-09`).
- **Approval** — `I-sheets-01` is enforced twice, at sheet build and at render, by
  `services/approval.py`. `adaptive` and `feedback` both create rows that only that
  gate may release.
- **PII** — `I-ai-01` (no name reaches a provider) rests on `I-scanning-07`
  (a crop never leaves the statement region), because the text gate cannot read
  pixels.
- **Never a zero** — `I-grading-04` and `I-scanning-05` say the same thing at two
  altitudes: an unreadable answer produces no attempt, never a score of zero.

---

## Companion reading

- [`../data-model.md`](../data-model.md) — every table, and the three places a
  column and a join table answer different questions
- [`../plan.md`](../plan.md) — the product, the milestones, the domain model
- [`../decisions-log.md`](../decisions-log.md) — the repo-wide D-numbers these
  documents cite
- [`../../CLAUDE.md`](../../CLAUDE.md) — the same rules, stated for whoever is
  writing the code
- [`../privacy.md`](../privacy.md), [`../mastery-model.md`](../mastery-model.md),
  [`../sheet-layout.md`](../sheet-layout.md) — the authorities for their subjects

---

**Last updated:** 2026-09-09
