# Decisions log

Choices made without stopping to ask, per §8.2 of the brief. Each entry records
what was decided, why, and what would make us revisit it. The ten most
consequential are repeated in [`handover.md`](handover.md).

---

### D1 · The answer grid is at a fixed position, not inline with the statements
Statement height varies with the text; a grid at a fixed position does not. The
detector can then find every bubble from the four fiducials alone, without
parsing a single word. Sixteen items per physical page (8 rows × 2 column
groups). **Cost:** the student reads the statement above and marks below, like a
standard optical mark sheet, rather than answering beside each question.
**Revisit if** teachers report the separation confuses younger classes.

### D2 · The UID is a 32-bit checksummed grid, not a QR code and not OCR
QR codes are explicitly out of scope, and OCR on a phone photo of a photocopy is
where these systems fail. The grid carries 24 payload bits + CRC-8. Verified:
**every single- and double-bit misread is rejected** rather than decoding to a
different real student. A failed decode asks the teacher; a wrong decode files a
child's answers under someone else's name.

### D3 · Class year is limited to 1–15 by layout v1
Four bits. Swiss Sek I is years 7–11, so this is comfortable. Encoding a higher
year raises at print time rather than producing a sheet that decodes wrongly.

### D4 · Mastery = accuracy × recency, two factors
Weighted recent accuracy alone is scale-invariant under uniform time decay, so a
perfect record would read as mastered forever and the "fading" band would never
fade. See [`mastery-model.md`](mastery-model.md) §1 for the constants and their
reasoning. **Revisit** once there is real cohort data to calibrate against.

### D5 · A blank answer is a graded zero; an ambiguous one is not graded at all
The student saw the item and left it — that is information. Two filled bubbles
is not information, it is a question for the teacher, and guessing between them
could score a child wrongly.

### D6 · Bubble fill is measured against a local annulus, not a global threshold
Found by the synthetic degradation suite: a global threshold reads a light
pencil mark as paper and silently scores the child zero, while a photocopy's
grey paper pushes it the other way. The local ring tracks both.

### D7 · A mostly-blank page distrusts its own blanks
A page where a light pencil did not survive the copier is indistinguishable from
a genuinely empty page at the level of one bubble — but not at the level of a
page. Above 60 % blanks, every blank is downgraded to low confidence and sent to
the teacher rather than scored zero.

### D8 · Offline `echo` and `hash` AI providers ship in the repo
`docker compose up` must work on a clean machine with no API key (definition of
done). Both are deterministic, so the demo seed and the tests are reproducible.
The real embeddings choice is [ADR 0001](adr/0001-embeddings-provider.md).

### D9 · The PII gate raises instead of redacting
Silently stripping a name would hide the bug that put it there. A leak is a
caller error and must fail loudly in development.

### D10 · Names are matched against the actual roster, not guessed by pattern
"A capitalised word" would flag half the mathematics vocabulary — Pythagore,
Zürich, Thalès. Redacting against the real roster is exact and has no false
positives on content.

### D11 · Curriculum data is not school-scoped
LP21 and PER are public reference data shared by every tenant. Everything else
carries `school_id`.

### D12 · Both curricula live in one `Competency` table
Discriminated by `curriculum` (`LP21` | `PER`) with a hierarchical `parent_id`.
A chapter maps many-to-many to competencies, so a teacher's textbook chapter can
reference codes from either. See [`curriculum.md`](curriculum.md).

### D13 · `open` exercises are stored and printable but never auto-graded
The grader dispatches on type and returns `NOT_GRADEABLE`. A future free-text
grader registers in `_GRADERS` and nothing else changes.

### D14 · State families derive `-100` and `-600` steps; the spec fixed only `-500`
Derived consistently for both themes and documented inline in `tokens.css`. In
dark mode the state `-600` step is *lighter* than `-500` so that text on the
dark `-100` tint passes AA — `primary-600` and `accent-600` keep the darker
button-edge role the spec assigned them.

### D15 · `--c-mastery-*` maps onto the state families
solid→success, ok→info, weak→warn, fading→danger, none→ink-300. An ordered
green→blue→amber→red→grey scale. The spec's `--c-ret-*` names are the same five
bands; `mastery` is the domain word used throughout this codebase.

### D16 · Responsive is a first-class requirement (added at user request)
The teacher uses a laptop at a desk and a phone in the classroom — scanning with
the phone camera is an explicit workflow. Mobile-first, drawer nav under `md`,
the matrix scrolling in its own container with a sticky name column, and
screenshot tests at 390 px and 1440 px. See [`plan.md`](plan.md) §9.

### D17 · Alembic gets one hand-checked initial migration, not autogenerate output
Autogenerate misses pgvector's extension creation and mis-orders enum types.
The migration is diffed table-by-table against `Base.metadata`.

### D18 · Tests run on SQLite with a test-only type swap for `Vector`/`JSONB`
CI stays fast and contributors need no Postgres for the unit suite. Integration
tests that exercise pgvector run against the Postgres service container.
