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

### D19 · The shipped brand library outranks the written brief
`docs/design/` (the "Craie Alpine" manual plus `alppy-brand-assets/`) arrived after
the first UI was built and contradicts the brief in three places. The assets win,
and the prose has been corrected rather than the assets adapted:

1. **The mark is "Le sourire"** — two slopes meeting at a summit with a smile in
   the valley, forming an **A** — not a slate crossed by a chalk stroke.
2. **The mark carries no mandarin accent.** The brief asked for a mandarin dot.
   The library forbids it, correctly: the accent is functional inside the product
   (it means AI-generated content) and putting it in the logo spends it on
   decoration. This is the stronger reading of the brief's own rule.
3. **`--c-mastery-ok` is `#86CF5B`**, a yellow-green, not the info blue that
   deriving the band scale from the state families produced (superseding D15).
   The shipped scale ships matching glyph colours at a constant luminance of 0.46
   and computed background opacities that keep the ramp monotonic in greyscale.

Pictogram stroke is **2.2** exactly, and the band glyphs are disc 4/4 · 3/4 · 2/4
· 1/4 · dashed ring — a coarse quarter-turn per band, because that survives a
photocopy and a 12 px rendering where a subtle density ramp does not.

Icons and illustrations are **generated** from the assets by
`packages/ui/scripts/generate-{icons,illustrations}.py` rather than transcribed by
hand, so refreshing the brand is a re-run and not a design exercise. The
illustration generator maps the flat export hexes back onto tokens (so the
drawings follow the theme) and **fails** if an asset introduces a fourth colour.

### D25 · The web app is hosted on Cloudflare Workers; the API is not

Hosting had to cost nothing for now, and Cloudflare's free plan can carry
`apps/web` — measured at **1.03 MiB gzipped against a 3 MiB ceiling**, with
static chunks served from Workers Assets without invoking the Worker at all.

It cannot carry `apps/api`, and this is not a matter of effort. Workers' Python
is Pyodide, so `opencv-python-headless`, `pymupdf` and `pillow-heif` have no
wheels to load — `alppy/scan/` is native code. Chromium (`sheets/render.py`)
does not fit a Worker. There is no Postgres, so no pgvector. Nothing on the free
plan runs a persistent process, so the arq worker has nowhere to live. **The
scanner is the reason the deployment is split**, and no amount of adapter work
changes that. The API goes on a host that runs containers, at roughly $5–10/mo;
R2 is the one Cloudflare piece the API does use, in MinIO's place.

The Worker doubles as the reverse proxy `next.config.ts` had always assumed:
`/api/v1/*` is rewritten to `ALPPY*API*ORIGIN`, so the browser sees one origin
and the host-only `alppy*session` cookie keeps working with no CORS and no
`SameSite=None`. The cost is that the API's address is compiled into the routes
manifest — moving the API is a rebuild, not a variable edit — and that the
origin cannot carry a port, because the route compiler reads `:8443` as a path
parameter. Both are written down in
[`deploy-cloudflare.md`](deploy-cloudflare.md) §4.

**Revisit if** the Worker outgrows 3 MiB, if a screen starts rendering data on
the server (there is deliberately no incremental cache configured, because
nothing today would fill it), or if a school requires Swiss data residency —
the Worker serves only the UI shell, but it proxies every API call, so
[`privacy.md`](privacy.md) makes that a change to this decision and not just to
the API's host.

### D26 · The builder navigates the document's own chapters, not just the teacher's

`Exercise.chapter_id` is inferred at ingest from competency overlap
(`pipeline._chapter_for`) and is legitimately `NULL`: it needs the teacher to
have created chapters, those chapters to carry competency codes, *and* the
extraction to have tagged the item. On a real textbook a large minority of rows
fail one of those. `_chapter_for`'s own docstring names the consequence — "an
untagged exercise is invisible to the builder's chapter filter, which is the
only way a teacher finds it".

So `SourceSection` was added: the chapter the *document* declares, read from its
headings at ingest (`ingest/sections.py`). It is a fact about the file, needs no
setup, cannot be null for an exercise that came from a page, and is how a
teacher actually navigates 400 pages. It is the builder's **primary** filter;
the curriculum chapter stays as the secondary one, because only that one answers
"fractions across every book I own".

Detection is deliberately conservative — short lines, alone, either carrying a
chapter word or a number plus a title-cased phrase, with running heads dropped
by repetition. A false heading shatters the outline into noise, which is worse
than a coarse one: a teacher can scroll twenty pages inside a correct chapter
and cannot find anything in ninety spurious ones. Sections are contiguous and
gapless, a document with no recognisable headings becomes one section covering
it, and pages before the first heading become a leading section rather than
being attached to chapter 1.

**Revisit if** teachers report bad outlines on real textbooks — the next step is
letting them rename and merge sections, which is deliberately not in this pass.

### D27 · A chapter is read by the model on first open, not at import

`MAX_EXTRACTION_CHUNKS = 200` used to be a per-*upload* ceiling: roughly the
first 50-80 pages of a book became exercises and the teacher was told to split
the PDF by hand. It is now the budget for eager extraction at import, and the
remainder of the document waits with `SourceSection.extracted_at IS NULL` until
somebody opens that chapter in the builder
(`POST /sources/{id}/sections/{sid}/extract`).

Two properties this keeps. **Nothing that worked before needs a click**: import
walks sections in book order and extracts while the budget lasts, so a
worksheet, a single chapter and every test fixture still arrive complete — and
it stops *before* a section that will not fit whole, because half a chapter is
the worst outcome available (the teacher sees exercises and cannot tell the back
half is missing). **A book nobody teaches from costs nothing**: a 400-page
textbook is indexed and searchable for the price of embeddings, and its
chapter 19 is never sent to a model unless someone asks for it.

De-duplication moved from a per-run set to `_existing_statements`, reading the
database. Sections are extracted separately and their page ranges abut, so a
chunk carrying the tail of one chapter and the head of the next could otherwise
offer the same exercise twice.

### D28 · A teacher-written exercise is its own origin

`ExerciseOrigin.TEACHER`, for items written with the builder's plus button.
Filing them under `TEXTBOOK` would claim a provenance they do not have — a
source filename and a page the teacher could check against the book on the desk
— and filing them under `AI_GENERATED` would put the mandarin accent on a
sentence a human wrote, which is the one thing that accent must never mean
(DESIGN.md §1). They need no approval gate: the teacher approved it by writing
it, so `approved_at` is stamped at creation and `approval.is_printable` keeps
working unchanged.

They are corpus rows rather than sheet-local ones, because `SheetItem.exercise_id`
is a non-null FK and because a teacher who writes a good true/false item should
get it back next term.

### D29 · A draft sheet is previewed by POST, and never stored

The builder shows the paper while the teacher is still reordering, which is the
only moment the information is worth anything — it is where a sixth exercise
turning into a second sheet, or a statement too tall for any page, becomes
visible *before* 72 pages come off the photocopier.

`POST /sheets/preview` takes the unsaved item list and renders it through the
same `SheetData`, the same templates and the same millimetre geometry as the PDF
(`build_draft_sheet_data`). The two alternatives were both worse. Redrawing the
page in React duplicates what `sheets/layout.py` owns and the scan detector
reads — the previous hand-rolled attempt put the bubbles inline instead of on
the fixed grid, printed no UID grid, and hardcoded A/B/C/D where the sheet
prints V/F. Creating a real draft `Sheet` and PATCHing it writes one
`SheetInstance` per student on every keystroke and abandons a row whenever the
teacher changes their mind.

The preview renders **one** copy, not one per student: it answers "what does
this sheet look like", and thirty near-identical copies would make the teacher
page through the class to reach page 2.

### D30 · The preview is closed by default, and the page count is not

Two working columns beat three cramped ones, so the A4 preview is behind a
toggle and the picker and composer get the room. The consequence had to be
designed for rather than accepted: with the preview closed, nothing would tell a
teacher that ticking forty exercises overflows a grid holding sixteen a page. So
the composer carries its own budget line — pages, `n / 64 max`, and an overflow
warning — computed from `SHEET_LAYOUT.itemsPerPage`. It reports the *floor* the
answer grid forces; the server preview remains the authority, because statement
height also decides the real page count.

### D31 · Scanned paper still needs OCR, and is still refused rather than faked

This is a **known gap**, recorded here so it is not rediscovered. The sheet
builder now reads a document's exercises, but `ingest.extract` still fails an
image-only PDF outright (`NO_TEXT_LAYER_ERROR`), because there is no OCR
anywhere in the repo. A teacher who literally scans an old paper worksheet gets
a `FAILED` source and a message telling them why — not a green tick over an
empty document, which is the failure mode that branch exists to prevent.

The builder handles it honestly: such a document simply never appears in the
picker, since only `SUCCEEDED` sources are offered.

The integration point when this is taken on is `extract.document_from_pages()`,
which already accepts pre-extracted text: an OCR pass ahead of `extract_pdf` in
`pipeline._ingest_fresh` feeds it without touching anything downstream —
`detect_sections` reads `PageText` and does not care where the text came from.

### D32 · `SOLID` is a stretch target, because skipping it inverted the ZPD

`TARGET_BANDS` excluded `MasteryBand.SOLID` on a defensible argument —
re-drilling a mastered competency spends a student's attention on what they
already have. The argument is right about re-drilling and wrong about the
student it actually described. With no gap in any band, `pick_gaps` returned
empty, `_plan_for_student` took its `diagnostic` branch, and a child who had
mastered everything assessed was handed `FALLBACK_DIFFICULTY = 2`: *easier*
work than they could already do, which is the precise opposite of the zone of
proximal development.

So `SOLID` is targeted at lowest priority and `target_difficulty` pushes it one
level **above** the working level rather than at it — the only direction in
which the clamp at 5 was ever reachable. `MAX_STRETCH_COMPETENCIES = 1` keeps
stretch from crowding out real gap work, with one deliberate exception: a
student whose competencies are *all* solid has no gap work to protect, so the
cap lifts and their whole sheet is stretch.

Two existing tests failed on this change and both were right to: they pinned
the old contract. They were re-encoded rather than loosened.

The change also nearly shipped a crash. `_BAND_WORDS` had no `SOLID` entry, so
`_gap_reason` would have raised `KeyError` the first time a stretch item was
retrieved. Rather than adding a word, stretch got its own phrase: "cible une
compétence acquise" reads as a mistake, and French `OK` already holds
"acquise", so the two would have collided.

**Revisit if** a teacher reports sheets that feel too easy for a strong class —
the next lever is an item quota rather than a competency cap.

### D33 · N groups is a partition above a function that already worked

`_plan_for_group` was always parameterised over an arbitrary `Sequence[Student]`
— it ranks the union of a group's gaps by how many of them need each competency
— and nothing in it assumed "the whole class". So N groups is `cluster_students`
placed *above* it and called once per cluster, not a second planner to keep in
step with the first.

The rule is stated the way a teacher has to be able to defend it: **students
with the same principal gap go together; if that gives more groups than you
asked for, the smallest merge, and if fewer, the largest splits by severity.**
Both existing modes fall out of it unchanged — `n_groups == 1` is today's single
shared sheet, and `n_groups >= class size` is today's per-student path — which
is why neither needed a different call site.

No group **entity** is persisted. The partition is recomputed from mastery every
time the teacher asks, so a stored group would be stale the moment the next scan
lands, and nothing downstream — mastery, attempts, scans — needs to know a copy
belonged to one. What survives is `SheetInstance.group_label`, a printed string,
and `Sheet.target = SheetTarget.GROUP`, which had sat in the enum unused since
0001.

The teacher can move a student between groups before exporting. That override
lives in the review screen's state and travels with the batch; a move takes the
receiving group's *items* as well as its label, because a sheet headed
"Groupe 3" holding group 1's exercises is the one outcome a move must never
produce.

**Revisit if** teachers want to name groups or carry them across a unit — that
is the point at which a `StudentGroup` row starts paying for itself.

### D34 · Feedback is its own document, because a page inside the copy misgrades the class

Per-student feedback had to reach paper. The obvious shape — one more page at
the end of each copy, which `html.physical_pages` already supports — is a silent
misgrading bug.

`scan_processing._copies_by_uid` recomputes each copy's pagination
independently, from the copy's **items**, and `process_scan` then maps a
photographed page with `page_in_copy = seen[uid] % len(printed_pages)`. A page
the renderer emits that this count does not know about rotates every later page
of that copy onto the wrong item list — with confident detections, and with
every unit test still green. `_stamp` would have written a wrong
`SheetInstance.page_count` for the same reason.

Making the two paginators agree (a shared "append a blank trailing page" helper)
would work, and was rejected: it makes the detector's page count depend on
*mutable* feedback state. Print a copy with feedback, discard the note
afterwards — `feedback_id` is `ON DELETE SET NULL` — and scan-time pagination
computes one page fewer than was printed. The same bug, reintroduced through the
back door.

So `SheetKind.FEEDBACK` is a third document beside the blank and the answer key,
built from its own `FeedbackData`, never passing through `paginate`. It carries
no fiducials, no UID grid and no answer grid: a page that is never scanned must
not *look* like one that is, and a stack of feedback pages fed into the scanner
by accident is rejected rather than read as blank answers for the child whose
UID is printed on it. `layout.py` is untouched, so this is **not** a layout
version bump.

### D35 · Generated feedback is grounded-only, and gated like an exercise

`adaptive_feedback` joined `providers.TRANSCRIPTION_PURPOSES`, so an ungrounded
provider returns an empty payload rather than inventing content. The reason is
stronger than the one that put `extract_exercises` there. An invented exercise
is a bad question a teacher can reject on sight; an invented misconception is a
claim about how one named child thinks, printed and handed to that child. The
offline `EchoChatProvider` cannot read its prompt, so anything it said about a
student's mistakes would be fiction with a real UID attached.

That required the echo provider to answer in the **caller's** empty shape —
`{"notes": []}`, not `{"exercises": []}` — because a feedback caller handed the
other envelope reports "the model did not return usable JSON", which blames the
provider for a refusal that is correct.

`MisconceptionNote.approved_at` mirrors `Exercise.approved_at` and is enforced
by the same module at the same two doors, batch creation and render. A note is
also only ever written from an answer we can actually read: an attempt whose
detection is missing, `LOW_CONFIDENCE`, `MULTIPLE` or `BLANK` is skipped rather
than guessed at, because explaining a distractor we did not read is exactly the
fabrication the grounding rule exists to prevent. A student with a clean paper
gets no note and costs no model call.

Generation runs as `JobKind.GENERATE_FEEDBACK` in the worker, not inside
`POST /adaptive/propose`: it is one model call per student, and a class of
twenty inside a request handler is a timeout with a half-written batch behind it
(CLAUDE.md — nothing blocks a request handler on a model call).

### D36 · The agenda is an append-only log, not a column per lifecycle moment

Every row already carried `created_at` and `updated_at`, and neither could
answer what a teacher asks of a term. `updated_at` is overwritten by whatever
edit came last, so it can never say when a pile was *confirmed*; and the two
moments that matter most to a chronology left no trace anywhere — **a sheet
going to the photocopier** (`rendered_at` is when the PDF was built, often days
earlier) and **a scan being confirmed** (a status enum flip, nothing more).

A column per moment would mean a migration every time the product learns a new
verb, and would still not give one ordered query across all of them. So `event`
is an append-only log with its own `occurred_at`, separate from `created_at`
because a pile corrected on Sunday carries Friday's lesson date.

`Event.subject_id` is deliberately **not** a foreign key: the log has to outlive
what it describes — deleting a sheet does not un-print it — and one column
cannot point at four tables. Titles are resolved at read time and fall back to
the stored `summary`, which is why `summary` is NOT NULL and may never hold a
student name.

`event_service.record` never raises and never commits. An agenda line is worth
less than the work it describes: a confirmed scan must not be lost because its
log row would not write.

`Sheet.derived_from_id` was added in the same pass. It is what makes a common
sheet and the differentiated sheets its results justify one teaching unit rather
than two rows with adjacent dates, and it is the edge a future unit view walks.

### D37 · The print→scan loop is a test now, not an argument

`layout.py` is the single source of truth for three consumers — the print CSS,
the PDF renderer and the scan detector — and nothing ever checked that they
agreed. `test_layout` proves the geometry is self-consistent, `test_sheet_output`
proves the HTML carries the right marks, and `test_scan_pipeline` drives the
detector from pages `scan/synthetic.py` draws. None of them put the real
renderer and the real detector in the same sentence, so the property the whole
product rests on — *a page Chromium prints is a page the detector can read* —
was argued rather than demonstrated, and the handover recorded it as unverified.

`tests/test_print_scan_roundtrip.py` closes it: render through Chromium,
rasterise the PDF at 200 dpi (roughly a phone photograph, deliberately not the
300 dpi a flatbed gives), and run `process_page` over the result. The page
registers, the pre-filled UID grid round-trips to `7B_01` with its CRC intact,
and every filled bubble on the answer key comes back on the right item.

It also asserts the negative that matters: the feedback document **must not**
register. A stack of feedback pages fed into the scanner by mistake would
otherwise be read as blank answers filed under the UID printed on each one —
which is the "never silently score a child zero" rule, arrived at from the
other direction (D34).

The test skips rather than fails when Chromium is absent, because a red test on
a machine with no browser says the code is broken when what is missing is a
binary. CI installs the browser so it actually runs there.

**The claim that Chromium was unavailable here was simply stale.** It was
installed; nobody re-checked. Worth remembering the next time a handover says
something cannot be verified.

### D38 · The agenda is backfilled from evidence, and only from evidence

`/timeline` on an existing database would have opened on an empty screen saying
nothing happened before the day the log shipped, which is untrue and is the
impression that stops a teacher opening it again.

`python -m alppy.cli backfill-events` reconstructs what real timestamps already
recorded: sources imported, chapters read, sheets created and rendered, scans
uploaded, and confirmation dated from the attempts' own `answered_at` — the same
stamp `confirm_scan` writes, so a pile corrected on Sunday still lands on
Friday's lesson. Idempotent by construction (the `(kind, subject_id)` pair is
the check), so it is safe in an entrypoint that runs on every container start.

It does **not** manufacture `SHEET_PRINTED`. Nothing ever observed a print —
that absence is half the reason the log exists — and `rendered_at` is a
different fact, often days earlier. An agenda that quietly infers is worse than
one with a gap: the teacher cannot tell which lines are evidence and which are
guesses, so every line loses its weight.

### D39 · Schema drift is a CI gate, because the unit tests structurally cannot see it

Five index drifts accumulated silently across migrations 0003–0005: `_fk()`
declares `index=True` on every foreign key, and four of those indexes were never
created, while `ix_exercise_discarded` existed in the database and in no model.

The reason none of it was caught is worth stating plainly: **the test suite
builds its schema with `create_all()` from the models**, which is precisely the
thing the migrations are supposed to reproduce. A test that constructs the
schema from the models can never tell you the migrations construct a different
one. The damage was not a slow query either — it was that
`alembic revision --autogenerate` proposed the same five every run, so a real
change arrived buried in noise nobody read any more.

Migration `0008` creates the four missing indexes.
`ix_exercise_discarded` is kept and declared in the model instead: it is a
partial index (`subject_id` where `discarded_at IS NOT NULL`) added deliberately
in 0004 for the "what has this teacher already rejected" query, and dropping a
working index to satisfy a diff would be the wrong direction.

`scripts/check-schema-drift.py` migrates a disposable Postgres from nothing and
diffs the result against `Base.metadata`; it runs as its own CI job. It needs a
real Postgres — SQLite cannot show this class of difference at all.

### D40 · A textbook exercise is cut from the page, not transcribed from its text layer

The first real book — *Mathématiques 10e* (MER), 228 pages, 504 exercises —
made the text path untenable. The text layer of a page hands a model
`3n²/n` as three tokens, a coloured rectangle as nothing, and the reading
order of a two-column exercise as a shuffle. A "precise" transcription of that
is not on offer. What the page does have is a **typographic contract**: every
exercise opens with a bold, coloured, body-sized line carrying a code and a
title (`NO64  Les quatre multiplications`), and the book marks a page overflow
with `SUITE ▶`.

`alppy.ingest.regions` reads that contract with PyMuPDF and cuts each exercise
out as a PNG at 200 dpi, stacking the pages of a continued one. The region ends
at the next header, at the book's own cross-reference line (`Fichier : …`), at
a section title, or at the page's content. On the real book it finds all 504,
each exactly once, and the nine continued ones (one over three pages) come back
whole; `tests/test_regions_real_book.py` holds those numbers and skips when the
47 MB file is absent.

Consequences, all deliberate:

* **The rows exist without a model.** Cutting costs nothing a teacher would
  wait for, so every coded exercise is stored at import — label, title, text,
  crop, size in millimetres — and is searchable and printable at once. A
  grounded model, when configured, *classifies and tags* within the existing
  per-import budget and the same whole-chapters rule; it never rewrites the
  statement. Without a model the chapter keeps its button and its notice says
  what is missing (`REGIONS_UNTAGGED_NOTICE`). A book with no coded headers
  yields no regions and takes the old text path unchanged.
* **Sections are the PDF's bookmarks when it has them.** The heading heuristic
  read this book's running head as forty-five two-page chapters. The publisher's
  outline gives the twenty it actually has.
* **The sheet prints the crop in place of the statement**, at the book's own
  size, shrunk only to fit the column or a 116 mm ceiling and never enlarged.
  (D41 later dropped the 0.65 minimum scale this first carried.) Under a
  picture there are **no ruled lines** — the book's exercises are worked in
  the notebook — because two token rules cost the millimetres that keep a
  second exercise off the page. The text stays as the image's alt and for
  search; a teacher's own wording prints above the picture.
* **The body-l floor does not apply to the crop.** The rule governs text Alppy
  sets; the crop reproduces the book's 10 pt Helvetica at 1:1, which is what
  the student reads in the book. Shrinking is bounded for exactly this reason.
* **The crop is inlined as a `data:` URI in the print document.** `html_to_pdf`
  loads the document from a string with no base URL, and the render worker must
  not fetch from the object store while Chromium waits. The web app gets an
  ordinary `figure_url` (`/api/v1/files/…`, tenant-checked, served as
  `image/png`).

### D41 · The sheet builder filters by chapter only, the folio is the student's, and a big crop shrinks

Three corrections from using the builder with a real book, 2026-09-07.

* **No curriculum-theme filter beside the chapter.** The picker offered the
  book's chapter (always set) and the inferred curriculum theme (often null).
  The chapter already says what the teacher is teaching, and a filter on a
  nullable field hid rows without saying so. The theme stays on the row and in
  the AI "propose" tab, where it is the only handle there is; it is no longer a
  second control on the document tab.
* **Page numbers restart per student.** The footer printed the document-wide
  folio, so student 18's first page read "36/72". A student holds their own
  copy and reads "1/2". The document-wide number is kept in `data-page` for
  collation; nothing on the printed face carries it.
* **Print prints the preview frame.** The button called `window.print()` on
  the app page, which printed the chrome, the tab strip and the A4 preview
  scaled to 42 % inside a scroll box. The preview iframe *is* the print
  document, served with the same `print.css` the PDF is made from, so the
  button now drives that frame (`allow-modals` on the sandbox, without which
  the browser ignores `print()`), and falls back to opening the document in
  its own tab when the frame cannot be reached.
* **A crop taller than the page is shrunk, never refused.** D40's 0.65
  minimum scale meant a half-page exercise imported, ticked and previewed
  cleanly, then failed the whole sheet — preview and PDF — with a message about
  one item. The crop is a raster at print resolution, so it stays sharp when
  small, and the preview shows the teacher how small before anything is
  printed. `figure_room_mm` now sizes the picture to the room left after the
  text the item prints above it (the teacher's own wording, MCQ options), so a
  figured item always fits a page on its own; `ItemTooTallError` is still
  raised for text, where shrinking is not an option.

### D42 · A written answer prints in a box that is measured, cropped, and graded on a verdict

The MVP printed four ruled lines under an open item and graded nothing. As of
2026-09-08 the item prints a delimited box and a vision model proposes a
verdict. Five choices were made without asking, and one with.

* **Height and fill are per sheet item, from presets.** 3, 5, 8 or 12 lines
  of 8 mm, filled with lines, the 5 mm notebook grid, or nothing — or no box
  at all (0 lines). Presets rather than a free height because pagination
  reserves room for exactly these; a fill choice because a drawing wants a
  grid and a sentence wants lines. Chosen by the user; the fill was added at
  their request. **The box prints under a textbook crop too** — D40's "no
  rules under a picture" stood for lines nobody read; a box the scanner
  crops is the common case, and the picture is sized to what the box leaves.
  "No box" is how a teacher keeps an exercise in the notebook.
* **Box geometry is measured, not computed.** A bubble sits where the layout
  says; a box sits under text the browser wraps, and the pagination estimate
  is deliberately generous. The alternative — pinning every item at its
  estimated top — would put uneven gaps on every printed sheet, including ones
  with no box. So the render job asks Chromium, in print media, for the border
  box of every answer box and writes one `AnswerBoxPlacement` per copy and
  page, keyed the way a detection is resolved (UID, folio, item index). The
  scan job reads those rows and never re-derives a box from `SheetItem`, or an
  edit after printing would move what the scanner crops (the D34 hazard for a
  rectangle). Re-rendering replaces the sheet's rows wholesale. Fiducials,
  UID grid and bubble grid did not move, so this is not a layout version bump.
* **Grading is a chained job, and nothing stays pending.** `PROCESS_SCAN`
  stays a pure OpenCV pass that flips the pile to review the moment the marks
  are read; the worker then enqueues `GRADE_OPEN_ANSWERS`, which settles each
  row as it lands. A failed call, an ungrounded provider and an unreadable
  answer all end as `NOT_GRADEABLE`. Confirmation waits **only while a
  grading job is queued or running** — confirming then would lock the pile
  with a child's answer unrecorded, and there is no second confirmation; when
  no job is coming, the pending rows are settled as not gradeable at confirm
  time and counted as skipped, so a dead provider delays verdicts but never
  holds the teacher hostage. A page assigned by hand queues its own grading
  job, since re-reading it can cut boxes the original chain never saw.
* **Images ride on the existing chat request.** `ChatRequest.images`, empty
  for every text caller, rather than a second provider protocol: audit, cost
  estimate and the text-side PII gate come for free, and the typed verdict
  lives in the scan layer where it is interpreted. The echo provider answers
  the grading purpose with a null verdict, never a grade drawn from a hash.
* **Template subtraction is geometric first, luminance second.** The border
  and corner ticks are painted out by position; the guides are painted out
  only inside their own bands, and only where the pixel is lighter than heavy
  ink, so pen crossing a guide survives. A light pencil stroke loses a
  millimetre where it crosses a guide; the model is told which guides the box
  carried. A box with no ink is `BLANK` without a model call.
* **The PII gate stays a text gate.** It cannot read pixels; what keeps a
  name out of a crop is that the crop is cut from the statement region only,
  and the renderer refuses to record a box outside it. The residual risk — a
  student writing their name in the box — is named in `docs/privacy.md`
  rather than pretended away.

Not done: cost. A class of 28 with three written items is 84 vision calls per
pile. The audit log prices them; nothing budgets them yet. Batching several
crops of one copy into one call is the obvious next step and is deliberately
not in this change.


### D43 · The expected answer of a written item is the teacher's, per sheet item, and optional

Until 2026-09-08 an open item's answer came only from the exercise: extracted
from the book, or typed when the teacher wrote the exercise in the builder. A
textbook exercise picked for a sheet had no place to write one, and the grader
was handed the words "(no expected answer was recorded)" and told to judge
against them. Three choices, taken without asking.

* **The answer lives on the sheet item, not the exercise.** `SheetItem.
  expected_answer`, beside `statement_override`, for the same reason the
  wording does: a teacher who rewords an item for this sheet needs the answer
  that goes with the rewording, and the corpus keeps the book's own. An empty
  field falls back to the exercise's `answer_text`; the builder shows that
  fallback in the field so the teacher sees what the key will print. A
  bubble item never keeps one — the service drops it, since the answer of an
  MCQ is the bubble. Not on the exercise, because a PATCH per keystroke on a
  shared corpus row from inside a draft is the wrong shape, and because the
  draft is deliberately unsaved until the sheet exists.
* **No answer means the model works one out, and shows it.** Prompt
  `grade_open_answer.v2` takes a *reference* block: the teacher's answer,
  which is then the only authority, or a sentence saying none was given, in
  which case the model solves the question first, judges against its own
  answer, and returns that answer. The grader keeps it in
  `Detection.reference_answer` — only when it had to produce one — and the
  review card shows it in place of the expected answer, so the teacher can
  overrule the reference and not merely the tick. A question that cannot be
  answered from its text (a figure, a table, an open-ended prompt) is told to
  return a null verdict, which lands as `NOT_GRADEABLE` as before; the
  never-a-zero rule from D42 is untouched.
* **The grader reads the sheet item's wording too.** It used to send the
  exercise's statement even when the printed one was an override. Same
  lookup, so fixed in passing.

Not done: a way to say "this book exercise has an answer, but grade without
one". Clearing the field falls back to the book's answer. Nobody has asked.

### D44 · The statement keeps its size; a box that does not fit follows on the next page, at any height

D42 sized a textbook crop to whatever the answer box left, so the item fit a
page on its own. With a twelve-line box that printed the book's type at a
size nobody could read (2026-09-08, seen on a real sheet). Two changes, the
first asked for, the second asked for in the same breath.

* **The box never takes room from the picture.** `figure_room_mm` no longer
  subtracts the box; the crop prints at its own size up to the D41 ceiling,
  less only the text printed above it. When statement and box together do
  not fit a page, the item is placed twice: the statement on its page with no
  box, and a *continuation* on the next — the number, "(suite)", and the box
  — each with its own page-local `item_index`. The box is moved whole, never
  split: a crop cut in two is two crops for the grader. The scan job records
  no detection for the statement part, so the exercise has one reading, on
  the page where its box is; the answer key prints the expected answer once,
  beside the box. Text items split the same way; a statement too tall on its
  own is still refused. Not a layout version bump: nothing at a fixed
  coordinate moved.
* **Any height up to fourteen lines.** The presets stay as shortcuts in the
  builder; "Personnalisé…" opens a number field. Fourteen is the tallest box
  that still fits the statement region alone once carried over (133.3 of
  134 mm), and `ANSWER_BOX_MAX_LINES` lives in `layout.py` beside the other
  numbers, with a test that fails if the continuation height and the ceiling
  ever disagree. The check constraint became a range (migration 0013).

### D45 · The builder takes its class and subject from the sidebar, and the sheet list is two piles, not one

The sheets screen listed every sheet as its own card with a status badge,
most of them called "Nouvelle fiche"; the builder repeated the class and
subject as two more selects above two tabs, said "Alppy produit toujours
deux documents" twice on one screen, and pointed its empty state "above" at
a select. Reworked on 2026-09-08 against the teacher workflows (manual,
from a book, from a scanned PDF), without dropping a feature.

* **Scope is the sidebar's.** The builder reads `useScope()` and shows
  "Pour 7B · Mathématiques" as a line under the title. A sheet built under
  one scope while the sidebar showed another was a sheet for the wrong
  pupils; one control, one truth.
* **The title is the heading.** A large borderless input, placeholder =
  the open chapter's title, which is also what the sheet is called if the
  teacher types nothing. "Nouvelle fiche" is the fallback of last resort.
* **The document belongs to its tab.** The select sits on the tab strip,
  beside "Depuis un document"; before any document is open the books are
  offered as buttons in the left column, and a teacher with no book is sent
  to import one.
* **An open item's settings are one line until opened.** "Cadre de 5
  lignes, lignes · réponse trouvée par le modèle" summarises the box and
  the expected answer; a native `<details>` opens the two controls. The
  defaults are right for most items, and twelve open panels were what made
  the composer unreadable.
* **The page budget is the composer's subtitle**, and the preview toggle
  sits beside it. The overflow warning stays. The "two documents" sentence
  now appears once, under the generate button, phrased as what you get.
* **The list is grouped by what is left to do:** "À terminer" (no PDF yet)
  and "Prêtes à imprimer", each one card with a divided list, a search box
  once there are more than six. Adaptive sheets carry a chip.

Not done: editing a saved draft in the builder (the API's `PATCH /sheets`
allows it; the list still opens `/sheets/[id]`), and units/phases from the
workflow document, which the data model does not have.

### D46 · The teacher's barème is a sheet default with per-item overrides, and it resolves at grading time

Points and penalties had no representation at all: `_grade_choice` returned
`1.0 if correct else 0.0`, and nothing in the schema, the API or the three
catalogues knew what an exercise was worth.

* **A sheet-level default plus an optional per-item override**, the shape
  `answer_box_lines` and `expected_answer` already established. `Sheet`
  carries `default_points_correct` / `default_points_penalty` NOT NULL;
  `SheetItem` carries the same pair nullable, where NULL means "follow the
  sheet". Both are tested with `is not None`, never for truth — a deliberate
  0 is a real choice (a warm-up worth nothing, an item that costs nothing to
  get wrong) and reading it as absent hands the item the default back.
* **The penalty is stored as a magnitude.** `scan.grading.score_for` is the
  single place the sign is applied, so a teacher who types `0.25` and one who
  types `-0.25` cannot mean two different things; the schema refuses the
  negative rather than guessing which was meant.
* **A blank is never penalised.** D5 already made a blank a graded zero, and
  every grader settles it before the barème is consulted. An ambiguous item
  is still not graded at all, so no barème reaches it either.
* **Points are gated on no exercise type.** Unlike the expected answer, which
  an MCQ never keeps because its answer is the bubble, a point value is
  meaningful everywhere — and an `open` item becomes auto-gradeable the moment
  a verdict arrives through `register_grader`. `open_grading` calls the same
  `score_for` as the two bubble graders, so the VLM path inherits the barème
  with no scoring logic of its own to fall out of step.
* **The mark and the mastery signal stay two quantities.** `Attempt.score`
  carries the points and may be negative or greater than one; `Attempt.correct`
  stays the boolean the mastery model reads, and `mastery_service` selects only
  that column. A barème that could move a mastery band would let a marking
  scheme silently rewrite what the model believes a child knows.
* **The total is computed, never stored, and floored at zero.** `SUM(score)`
  over attempts is as fresh as the attempts themselves; a stored total would be
  a second place to disagree with them the first time one detection is
  corrected. Per-item scores stay signed so the teacher can see which answers
  cost points — only the sum is clamped, because a mark below zero says nothing
  a report can use.
* **The barème resolves live, at grading time, not frozen at print time.**
  Deliberately unlike an answer box's rectangle (I7): a rectangle is a physical
  fact about a page the browser laid out, and recomputing it crops the wrong
  pixels from a real photograph. A barème touches no coordinate — it is
  arithmetic applied after every physical fact is fixed. The correctness key
  beside it has always resolved live (fix a typo'd answer after printing and
  the pile grades against the fix), and freezing what an answer is *worth*
  while leaving what it *is* live would split one question down the middle.
  Editing it nulls the PDF keys, because the paper prints the points.

Cost: a sheet whose barème changed after printing grades on the new one. That
is the intent — a teacher who reweights after seeing how a class did wants
exactly that — but the printed "(1 pt)" on the paper in the pile is then stale,
and only the "needs re-render" signal says so.

### D47 · A crossed box reads as readily as a filled one, by shape rather than by density

The sheet now tells the student to fill the box **or** cross it. The detector
was tuned entirely for fills: `FILL_MARKED = 0.35` wants 35% of the disc dark,
and the whole degradation suite drew marks as a solid disc at 75% radius. A
hand-drawn X covers roughly a quarter of the sampled area. Left alone, every
crossed answer in a class would have landed in the uncertain band and been
handed back to the teacher — the pipeline working perfectly and being useless.

* **Not a layout version bump.** The bubbles do not move. Sheets already
  printed keep registering against v1, which is the whole reason the geometry
  was left alone rather than switched to squares.
* **Shape, via an angular ink profile.** Bin the ink in the OUTER band of the
  disc by angle and count lobes: a filled disc lights every bin, a stray line
  gives two lobes 180° apart, a cross gives **four**, a smudge gives none.
  Two crossing strokes cut the rim in four places at *any* rotation, so there
  is no angle threshold and a leaning X reads like an upright one. The middle
  of the disc is excluded deliberately — a cross's own intersection and a
  rubbed-out answer both put ink there and neither can be told from the other.
* **A Hough transform was designed and rejected.** It finds the two stroke
  orientations more literally, but needs seven interacting empirical constants
  on a 32 px patch and none are derivable. The lobe count needs two, and the
  docstring explains itself — which matters in a file where `0.82` and `1.6`
  carry paragraph-long justifications.
* **`max(fill, mapped_cross)`, and the cross score is gated to exactly 0**
  unless the structure is confirmed. So for every bubble that is not crossed,
  `mark` *is* `fill` and every judgement the module made before is unchanged —
  the 32 existing degradation tests passed untouched, which is the guarantee
  the gating buys. Blending would drag a real cross back under the threshold,
  which is the problem being solved: a thin X *should* have low density.
* **The mapping anchors three points** (`CROSS_BLANK`→`FILL_BLANK`,
  `CROSS_MARKED`→`FILL_MARKED`, a perfect cross→`FILL_MARKED × 1.6`) so the two
  scales agree wherever either has a name, and an unmistakable X is not
  reported as barely-a-mark. The MULTIPLE test keeps working across
  conventions: a cross and a fill on one item compare on the same scale.

Measured: crosses read at 0.96–1.00 confidence across the full degradation grid
(rotation, perspective, two-generation photocopy, uneven light, noise, JPEG,
rescale, phone photo, copier) and down to `pencil=0.45`. A fine-pen cross whose
density falls *below* `FILL_BLANK` — which D5 would otherwise make a silent
graded zero — is recovered and read.

Not done: the shape test wants an **X**. A checkmark gives two lobes, not four,
and reads as low confidence — surfaced to the teacher, never scored zero, but a
class that ticks rather than crosses will fill the review queue. The printed
instruction names the two conventions the detector actually knows. Roughly one
fine-pen cross in twelve is not resolved into four arms either; that reading is
refused rather than guessed, and `test_a_fine_pen_cross_is_never_silently_scored_zero`
pins the guarantee that matters — the failure is always "handed back", never
"scored zero".

### D48 · "Revised" is derived from a count, not a fourth `ScanStatus`

A pile can be signed off, reopened, and signed off again. That is a fact about its
history, not a status: `Scan.status` answers "is this signed off?" and a revised
pile still answers yes. Adding a `REVISED` member would turn every
`is ScanStatus.CONFIRMED` check into a two-member test — three in the service, one
in the web app, four in the tests — and each one missed silently unlocks a pile.
`confirmed_at` / `reopened_at` / `confirmation_count` carry the history instead, and
`revised = confirmation_count > 1` is computed at the edge. Not one existing status
check moved. Full argument in `docs/features/grading/decisions.md`.

### D49 · Points and mastery are two screens, not two columns of one

The five-band ramp is calibrated — monotonic in greyscale, constant glyph
luminance — and it encodes decayed evidence about a competency. A score is what the
barème says one paper was worth. Colouring a score with that ramp asserts a band
nobody computed. `Matrix` was extracted from `MasteryMatrix` so the two share the
keyboard model, the sticky column and the contained scroll, and share no vocabulary;
`MasteryMatrix`'s public props are unchanged.

### D50 · An ungraded result is null, at every level

`null` in the SQL, on the wire, in the TypeScript type, and an em dash in the cell.
`aggregatePoints` sums `possible` over graded entries only, so an unmarked sheet
cannot enlarge the denominator. Coalescing to 0 anywhere reads as a failure the
pupil never had — the same mistake as scoring an unreadable answer zero (D5), one
altitude up.

### D51 · Reopening re-derives from the detections rather than keeping history

`grade_item` is pure, `Detection` rows survive confirmation, and mastery is already
a pure recompute over attempts. So reopening deletes the attempts the pile owned
and replays the grader over the newest *other* still-confirmed reading for each
freed item. The one fact that had to be stored is `Attempt.confirmed_scan_id`:
`detection_id` names the reading, not the pile that currently owns the grade. An
item with no older reading simply has no attempt again — not a zero.

Cost: a confirmed pile is now read-only. Correcting or reverting a reading is
refused until it is reopened, because the grade was computed from the reading as it
stood and editing one underneath leaves the two disagreeing. `correct_detection`
previously had no such guard at all — only the review screen's `readOnly` prop.


### D48 · Design rules get numbers and an enforcement column, but not a folder each
A design-documentation framework was dropped into `docs/design/` proposing three
documents per component (`README` / `specifications` / `decisions`), a `DC-*`
constraint register, Figma and Storybook links, semantic versioning of the
design system, and a design-lead approval gate.

Most of it duplicates what this repo already has, and duplicated documentation
rots at a different rate from the original. `DESIGN.md` is already the
specification — tokens, scale, recipes, print geometry — and this log is already
the decision record, with a stronger format than the one proposed (alternatives
*and* the revisit condition). Splitting either across ~30 component folders would
turn one file a reader can hold in their head into thirty they will not open, and
the values in the example material were generic (`#0066FF`, Inter, 4 px radius,
14 px body) — the exact opposite of every rule in §2, §3 and §4 here.

**Taken: the constraint layer, which was genuinely missing.** The rules that
break the product when violated existed only as prose, spread across `DESIGN.md`
§1 and `CLAUDE.md`. They had no identifier to cite, no statement of what enforces
them, and no statement of what failure looks like. `docs/design/constraints.md`
gives each one a `DC-<area>-<nn>` id and three columns; `DESIGN.md` §1 and the
`CLAUDE.md` rule list now carry the ids, so the prose and the register point at
each other rather than drifting.

Two of those columns do real work. **Enforced in** is written honestly, so
`review only` is a visible admission that nothing in CI will catch a rule — the
register doubles as a list of what is worth automating next. **Failure symptom**
is the entry gate: a rule with no describable symptom is a preference, and stays
in `DESIGN.md` as a spec instead. That is what keeps the register from growing
into a style guide nobody enforces.

**Rejected:** per-component folders (duplicates `DESIGN.md` §6); Figma and
Storybook links (neither exists); a versioned design system with a changelog and
an approval gate (a single-maintainer repo where `main` always builds — git is
the changelog); and every literal value in the example material, per D19 — the
shipped assets outrank prose, and generic prose outranks nothing.

**Cost:** a rule now lives in two places — its prose in `DESIGN.md` or
`CLAUDE.md`, its row in the register. The tags are the mitigation, not a fix.
**Revisit if** the register drifts out of step with the prose twice, at which
point the prose lists should shrink to pointers and the register become the only
statement of a load-bearing rule.

### D52 · A results breakdown renders answers, not bubble indices

`_readable_choice` turns a detected index into the letter and option text using the
same `OptionLetters` / `tf_letters` the sheet was printed with, so the screen says
what the paper says — V/F on a French sheet, R/F on a German one. Formatting it in
React would duplicate a print-geometry fact from `layout.py` and the sheet's own
language, and eventually disagree with the paper.

### D53 · Every graded item has three states, not two

Right, wrong, and never graded. `correct: null` / `points_earned: null` reach the UI
as a "non noté" badge and a dash. Collapsing the third into "wrong" is the same
mistake as scoring an unreadable answer zero (D5), shown to the pupil whose paper it
is.

### D54 · The longest wait in the product gets the loudest indicator

Uploading a pile of 28 photos is tens of megabytes and the only feedback was one
grey line of text. A teacher who cannot tell whether anything is happening puts the
phone down, and the upload dies with the page. The busy state is now a panel with a
count of the files in flight, and it says to keep the page open. The
processing that follows already had a progress ring on the review screen, fed by the
job the upload response names.

`ProgressRing` was the wrong component for it: a ring is a *meter* — it reports a level that is
known — so drawing one at 0 for an upload nobody is measuring says "nothing has happened yet".
`Spinner`, which already existed privately inside `Button`, is now a shared component and is the
idiom for an indeterminate wait; the ring stays for jobs that report a real fraction.

### D55 · A job's `message` is a log line, not UI copy

The review screen showed `Job.message` verbatim while a pile was being read, so a
French teacher was told "queued for registration and detection" beside a meter
reading 0. Those strings are written for the worker's log and are English by
construction; nothing in three catalogues could ever translate them.

The waiting state is driven by the job's `status` and `progress` instead — queued
gets a spinner and "Analyse en attente…", running with a real fraction gets the ring
and "Lecture des copies…", and a sub-line says what Alppy is doing and that the page
can be left open. The server string never reaches the screen.

The stage badge follows: it reads "Analyse en cours" while the pile is being read,
not "À valider", which asked the teacher to act on something that did not exist yet.

And the number is stated once. The ring carries the percentage; the words carry the
activity. Saying "42" in both was two answers to one question.


### D56 · A Theme hangs from ONE Competence, chosen per school, and still tags many

`chapter_competency` is a many-to-many on purpose: it is what lets the chapter
"Pythagore" carry `MSN 31.2`, `MSN 31.1`, `MA.2.A.2` and `MA.2.C.1` at once, so a
teacher in Sion and a teacher in Chur can share a chapter while each reports against
their own official text (`docs/curriculum.md` §3). That design stays.

But a many-to-many cannot say where a chapter *sits* in a tree. Navigation and
roll-up both need exactly one parent per node, and picking "the first tagged
competency" would have made the tree depend on JSON array order.

So `Chapter.primary_competency_id` is a new, nullable FK: the single canonical
parent. Because `Chapter` is already school-scoped — every school gets its own copy
of the seeded chapters — "per school, per curriculum" needs one column, not two:
`chapters.json` carries `primary_competency_code` keyed by curriculum, and the seed
loader resolves whichever one matches `School.default_curriculum`. A PER school files
Pythagore under `MSN 31.2`; an LP21 school files the same chapter under `MA.2.A.2`;
both still credit all four codes for mastery.

The primary must be one of the chapter's own `competency_codes`, and the loader
raises if it is not — otherwise a chapter could sit in a branch it does not teach.

Cost: one more field to keep in step in the seed data, and a second concept
("primary" vs "tagged") that a reader has to hold. The alternative was reversing the
cross-curriculum design outright, which would have split the seven seeded chapters
into fourteen and made a shared chapter impossible.

Revisit if a school ever needs to teach both curricula at once, which would make
`default_curriculum` the wrong place to resolve from.

### D57 · A class declares the Branches it studies; it no longer infers them

`class_service.subject_ids_for_class` was `SELECT DISTINCT sheet.subject_id`. That is
circular: the Branch level of the navigation only existed once a sheet had been built
inside one, so a brand-new class opened onto nothing and the teacher had no way to say
"7B does maths, French and German" except by making a sheet.

`class_subject` (class_id, subject_id, position) makes it a fact. It is backfilled from
exactly the query it replaces, ordered by `MIN(sheet.created_at)` — first-use order,
which is what the column means, not alphabetical.

Nothing new is asked of the teacher: `sheet_service.create_sheet` calls
`class_service.declare_subject`, which is the one place a class and a subject first
meet. So the table stays populated the way the derived query stayed correct, and the
insert is `ON CONFLICT DO NOTHING` so two sheets created at once in a new subject
cannot race into a duplicate-key error on an ordinary action.

Rejected for this pass: a teacher-facing endpoint to add and reorder branches. It is a
real feature with its own review; `declare_subject` alone restores current behaviour and
removes the circularity.

### D58 · A rolled-up band is an evidence-weighted mean, and it says its own coverage

`docs/mastery-model.md` §6 said plainly that competencies were treated as independent —
there was no aggregation above `(student, competency)` at all. A Branch → Competence →
Theme navigation needs a number at every level, so `roll_up_mastery` is new work.

**Rule: the evidence-weighted mean of the children's scores, weighted by
`effective_n`.** Two alternatives were rejected:

*Worst-band-wins* would make every Theme read as the worst thing in it. With three or
four competencies per chapter that is "amber or red, always" — a constant, not a signal.
`_weakest_first` sorts *students* by their weakest cell; that is a triage order, not a
claim that a group's mastery equals its minimum.

*Plain mean* would let a competency backed by one lucky guess pull the aggregate as hard
as one backed by twenty confirmed attempts. `compute_mastery` already refuses to do that
a level down — it is what `effective_n` and `MIN_EVIDENCE` are for.

A never-assessed child has `effective_n == 0` and contributes no weight, so "not yet seen
is a band, not a zero" holds one level up unchanged. When every child is unassessed the
roll-up is `NONE`, through the same `band_for(has_attempts=False)` path the leaf uses.

Rejected early, and worth recording because it is the obvious idea: **pooling the raw
attempts** of every competency in a Theme and running `compute_mastery` once. It is
simpler and it is wrong — one recency would be derived from the mixture, so a competency
practised last week would launder the staleness of one last touched in June, in a model
whose whole purpose is fading. Pooling across *students* is fine and is what
`mastery_service.pool_by_competency` does; pooling across competencies is not.

Two costs, documented rather than hidden. `score == accuracy × recency` holds at a leaf
and **not** at a roll-up: `score` is the mean of already-decayed scores, and
`accuracy`/`recency` are means kept for display, so re-multiplying them would decay the
same evidence twice. And `days_until_review` is the *earliest* of the assessed children's
rather than a re-derivation — a weighted mix of differently-aged decay curves has no
closed form worth shipping, and "whichever competency comes due first" is the more useful
thing to act on anyway.

Because an aggregate band can hide its own coverage — green over one assessed competency
and green over three look identical — `TreeMasteryOut` also carries `assessed_count`,
`child_count` and `weakest_band`, and the UI shows them beside the band (DC-colour-08 at
a level where a bare colour is most tempting).

### D59 · The builder is rooted on the Theme, and "Sans thème" is what keeps that honest

`ExercisePicker`'s docstring promised a property — **nothing is unreachable** — and kept
it by *not* offering a curriculum-theme filter at all: `Exercise.chapter_id` is inferred
(`ingest.pipeline._chapter_for`) and null on a large minority of a real textbook's rows,
so filtering on it hid exercises without saying so.

The hierarchy makes Theme the builder's root, which reverses that. The property does not
go away; it changes from being guaranteed by omission to being guaranteed by design:

- `ThemePicker` pins a **counted "Sans thème (N)" row at the root of its tree**, sibling
  to every Competence rather than nested inside one, **rendered even when N is zero**.
- Choosing it sends `chapter_id=none` — a real sentinel, distinct from the parameter
  being absent. Absent means "no theme filter"; `none` means "the untagged ones". Without
  that third answer those rows would have no selector at all.
- A sheet can never be *filed* under it. It is a corpus question, not a filing.

If that row is removed, or hidden when its count is zero, untagged exercises silently
become unreachable again — which is the exact regression the original decision existed to
prevent. It has a constraint id (`DC-content-06`) for that reason.

Note this pseudo-node is **not** the `unfiled` Chapter (D60): that one is where a sheet
nobody has filed is stored; this one is a filter over exercises. Two similar names, two
different objects.

### D60 · Every sheet has a home Theme, and "unfiled" is the honest one

`Sheet.chapter_id` is NOT NULL: a sheet's place in the tree is a fact, not something each
screen re-derives from its items.

Existing sheets have nothing to backfill from. The tempting source — a majority vote over
`sheet_item → exercise.chapter_id` — is itself the unreliable inference above, and
promoting a second-hand guess into a teacher-facing filing the teacher never confirmed is
exactly what `Exercise.approved_at` and `MisconceptionNote.approved_at` exist to prevent
elsewhere. So every existing sheet moves to a per-subject `unfiled` chapter, which says
the true thing, and the teacher re-files it when they care (`PATCH /sheets/{id}` gained
`chapter_id` for that, and it is the path that matters most the week this ships).

`unfiled` is identified by its `key` but **excluded by `primary_competency_id IS NULL`**.
Those are deliberately two different tests: a school may relabel the bucket, and a rename
must not readmit unfiled sheets into a mastery number.

It is created eagerly by migration 0016 and by the reference seed, and **lazily** by
`chapter_service.ensure_unfiled_chapter` when a subject somehow has none. The laziness is
the point: a missing structural row would otherwise surface as a 422 on an ordinary "new
sheet", which the teacher can neither understand nor fix. A missing infrastructure row is
ours to repair, not theirs to report.

A differentiated batch inherits its source sheet's Theme rather than falling back to
`unfiled`: the reprise on fractions belongs next to the sheet whose results justified it,
and a Theme inferred from its generated items would scatter one teaching unit across the
tree.

### D61 · `/adaptive/batch` validates `source_sheet_id`, and a chapter key is unique per subject

Two corrections found while reviewing D56–D60, both worth recording because each
changes an observable behaviour.

**`source_sheet_id` is now resolved through `sheet_service.get_sheet`**, which carries
the school *and* ownership check (D23). `/adaptive/batch` performs none of its own —
unlike `/adaptive/feedback`, which has called `get_sheet` all along. Before this the
id was filtered on `school_id` alone when inheriting the parent's Theme, and not at
all when stored on `derived_from_id`; `sheets/render.py` reads that column and prints
the source sheet's title onto the feedback page, so a colleague's — or another
school's — sheet title could reach paper it has no business being on. A sheet the
caller cannot see is now a 404, where it used to be silently accepted.

**`uq_chapter_key` on `(school_id, subject_id, key)`.** `chapter_service.
ensure_unfiled_chapter` is called on the first sheet ever created in a subject, which
is exactly when the bucket does not exist yet; two of those at once both saw nothing
and both inserted, and the subject's unfiled sheets then split silently between two
buckets with no error. The constraint makes the `ON CONFLICT DO NOTHING` mean
something.

`POST /chapters` never checked for a duplicate key, so existing data may violate the
new constraint. Migration 0016 **renames** the later rows (`fractions` → `fractions-2`)
rather than deleting them: a teacher's chapter, and whatever `Exercise.chapter_id`
points at it, is not a migration's to throw away. The endpoint now returns 409 rather
than letting the constraint surface as a 500.

Also noted and deliberately not "fixed": two subjects declared for the same class in
the same instant can be assigned the same `class_subject.position`, because the
primary key is `(class_id, subject_id)` and `ON CONFLICT` cannot serialise that. Rather
than locking a row on an ordinary sheet creation, `subject_ids_for_class` breaks the
tie on `subject_id`, so the branch order is arbitrary in that rare case but never
wobbles between requests.

### D63 · Adaptive targeting reads the sheet the teacher just corrected

Targeting read all-time `MasterySnapshot` rows; `source_sheet_id` was on the request and
recorded lineage only. `services/performance_summary.py` now rolls one sheet's attempts
up per competency through the same `mastery.model`, and that wins where it says
anything; mastery is the fallback, and "no evidence at all" is reported as a diagnostic
rather than looking like a child with no gaps.

The summary reports its own limits, because each is a way it could lie: attribution is
many-to-many so a roll-up does not partition; the attempt join is an inner join on
`exercise_competency`, so items nobody tagged are invisible and are counted separately;
and attempts only exist after a scan is confirmed, so `answered` and `printed` are both
reported. `targeting_basis` and `evidence_partial` reach the screen — a teacher who has
to defend a sheet needs to know which evidence chose it.

Full reasoning in [`docs/features/adaptive/decisions.md`](features/adaptive/decisions.md).

### D64 · An LLM may revise a partition, never decide it

`cluster_students` stays the default, the seed and the fallback. `llm_grouping` is
opt-in per request; the model's answer is validated against the roster and **rejected,
not repaired** if it drops a child, seats one twice, invents an id, empties a group or
misses the requested count. `adaptive_cluster` is a transcription purpose, so the
offline provider returns nothing and CI takes the deterministic path — which is the
correct answer, not a degraded one.

**Rejected:** letting the model decide with the deterministic rule only as an error
fallback. D33's rule exists because a teacher has to state it to a parent, and a
regrouping nobody can justify is worse than no regrouping.

### D65 · Generation is batched, and the isolation that costs is bought back

Plans register a generation *ask* with a collector; one pass fills them all, eight plans
to a call. Measured honestly: ~25–35% of input tokens and **zero** output tokens saved,
against output costing ~5× input — the win is latency and round-trips, not spend, and
that is recorded so nobody re-derives the wrong expectation from the diff.

One call for eight plans breaks I-adaptive-09 unless it is bought back, so: a content
failure is isolated per plan, and a transport failure retries the chunk **once, split
into single-plan calls**. It also fixed a live bug — `seen` was rebuilt per call, so two
groups in one run could be handed the identical statement.

`test_one_students_failure_does_not_cost_the_rest_of_the_batch` pinned the invariant to
a shape rather than to the invariant, and was re-encoded for the split path rather than
loosened, as D32's tests were.

### D66 · Proposing an adaptive batch is a job, and the proposal is not its result

`POST /adaptive/propose` made every model call for a class inside the request handler —
the thing CLAUDE.md forbids outright, and which `generate_feedback`'s own docstring
already argued against. It is now `JobKind.PROPOSE_ADAPTIVE` (a new value:
`GENERATE_ADAPTIVE` renders and generates nothing, despite its name).

The proposal lives in `AdaptiveProposal`, read by `GET /adaptive/proposal/{job_id}`, not
in `Job.result`: the screen polls the job every 900 ms and a class of 24 is close to a
megabyte, so a status row has to stay cheap to ask about.

Two things the move would have broken quietly and did not: `propose_adaptive` used to
`db.commit()` under a task that owns the transaction boundary, and the AI rate limit
would have stopped covering the model calls it was there to throttle — so the limit
stays on the handler and an in-flight check returns the running job instead of starting
a second.

### D67 · OpenAI is the default chat provider, and the pair is validated at startup

See [`docs/adr/0002-chat-provider.md`](adr/0002-chat-provider.md). `ALPPY_OPENAI_API_KEY`
follows the `ALPPY_` convention rather than the briefed bare `LLM_API_KEY`, because with
two providers a single key variable cannot say which vendor it belongs to.

`ai_chat_model` defaults to empty, meaning "this provider's default"; a model id
belonging unmistakably to another vendor raises on load, because a `claude-*` id sent to
OpenAI 404s every call in the product *and* the audit row would name a model that was
never called. A provider whose own key is missing falls back to `echo` and logs
`ai.provider.no_key` — with two real vendors, "has the other one's key" became a way to
be silently offline while everything still appeared to generate.

Temperature is treated as a property of the model, with a prefix table for the known
cases and a runtime-learned refusal behind it. `grade_open_answer.v2.md` states
"temperature 0.0 — a grade must be reproducible, never creative" in its own front
matter, so `ai.temperature.dropped` on that purpose is a signal to change model, not a
line to ignore.

### D68 · The prompt log is a second store, not a wider audit row

`ModelCall` stays content-free: `docs/privacy.md` §3 offers it as what a school shows an
auditor, and content in it would make the audit table the leak it exists to detect. The
full prompt and response go to `PromptLog` instead — **off by default**, capped per
field, swept by `python -m alppy.cli purge-prompt-logs`, and written only *after* the
PII gate passed. A blocked prompt records the refusal and no content at all: the string
that fired `PiiLeakError` is by definition the one carrying a roster name.

Captured inside `AiClient.complete` rather than in a provider wrapper. A wrapper would
lose the prompt name and version, and would have to re-declare `grounded` on behalf of
the provider it wraps — one forgotten attribute away from letting the offline stand-in
claim it had read a textbook page.

**Rejected:** an HTTP endpoint to read it. The store holds prompt content and exposing it
needs an authorisation story that does not exist yet; the query path is SQL and the CLI.

