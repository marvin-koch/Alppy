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

### D62 · Demo mode is a flag that defaults to off, in both halves

A demo instance should not ask for an account. The obvious implementation —
delete the session check — is the wrong one: `Student.first_name`/`last_name`
hold children's real names, and the session cookie is the only thing between
those and anyone with the URL (docs/privacy.md).

So it is a flag, `Settings.demo_mode`, default **False**, and deliberately not
derived from `env` or `debug`. A flag that can switch itself on from another
signal is one that eventually switches itself on somewhere real; the test
`test_debug_and_local_env_do_not_turn_demo_mode_on` pins that.

It is a fallback for the ABSENCE of a cookie, never an override of one. A
teacher who signs in on a demo instance is still themselves, or the ownership
rules every read depends on (D23) would answer for somebody else.

**Both halves have to be set, and they are separate on purpose.**
`ALPPY_DEMO_MODE` opens the API; `NEXT_PUBLIC_ALPPY_DEMO_MODE` tells the web
middleware to stop redirecting to `/login`. The middleware gate is a routing
convenience rather than the security boundary — its own docstring has said so
since it was written, and the cookie is `httpOnly`, so presence is all the edge
can check. Setting only the API leaves a visitor stranded at `/login`; setting
only the web drops them into an app whose every request 401s. Neither half is
dangerous alone, which is the point: the dangerous state needs two deliberate
acts, not one.

The demo teacher is resolved by email (`demo_teacher_email`) rather than "the
first teacher in the table", so an instance holding two schools cannot quietly
start answering as whichever sorts first. If demo mode is on and no such
teacher exists the API says so instead of returning 401, which would send the
reader hunting for a login that could not have helped.

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

### D69 · A student sits in many classes, and exactly one of them minted their UID

`student.class_id` carried two facts that only looked like one while a child belonged to
a single class: **whose pupil is this** and **which classes does this pupil attend**. A
teacher who takes 7B for maths and also runs a support group could express neither
separately, and every roster, matrix, tree and printed pile read the first as though it
were the second.

Split the way D56 split `Chapter`: where a row *sits* is a column, what it *belongs to*
is a join table. `student.home_class_id` is the class that minted `uid` (`7B_15`) and
`number`; `class_student` is who actually sits where. The UID stays single-valued and
home-minted, which is why nothing in the print or scan path changed — the identifier on
paper is a fact about the pupil's home, unique per (school, school_year), and the
detector decodes it exactly as before.

**The column was renamed rather than kept.** A dozen read sites had to be judged one at a
time as "enrolled" or "home", and under the old name every site nobody reviewed would
have gone on compiling with the old meaning. The worst of them, `scan_processing`'s
`wrong_class` test, *clears every detection on the page*: a co-enrolled pupil's answers
would have disappeared with no error anywhere for the teacher to see. Renaming turned
each unreviewed site into an `AttributeError` the suite catches instead.

`home_class_id` is **RESTRICT** where `class_id` was CASCADE. Deleting a class deleted
its students, and `attempt`, `mastery_snapshot` and `sheet_instance` all cascade from
there — a term of evidence gone for a child who was also sitting elsewhere. Unenrolling
drops one join row and refuses on the home class; deleting a student stays the only
operation allowed to destroy evidence.

**Ownership (D23) is unchanged but now reads over a set of classes.** A pupil co-enrolled
in two teachers' classes is readable by both — that is the feature — and `enroll` asserts
that the student and the class share a school *and* a school year, because
`uq_student_uid` is scoped per year and an enrollment spanning two would make a printed
UID ambiguous. A reviewer reading `_owned_student` in isolation will otherwise read the
widening as a regression.

**Rejected:** per-enrollment state beyond `enrolled_at`. The moment `left_at` exists,
every roster read grows a temporal predicate and every test needs an injectable clock.
Leaving a class is a deleted row.

**Shipped in two parts.** The migration backfills one enrollment per student equal to
their home, and nothing can create a second until the enroll/unenroll endpoints ship — so
this release is provably behaviour-preserving on a change that touches the scan path.

### D70 · A sheet answers several sheets, and one of them is the principal

`Sheet.derived_from_id` held one parent. A reprise legitimately answers more than one
thing — the test whose results triggered it, and the earlier worksheets whose gaps it
revisits — and there was nowhere to say so.

`sheet_source` is the set; the column stays, because they are different facts. The column
is where the sheet **hangs**: what the feedback page prints, what the tree draws, what D61
validates. The table is what it is **about**. Position 0 is the principal and is the same
sheet as the column — `sheet_service.set_sources` writes both together, because a sheet
whose feedback page names one parent while its lineage draws another is worse than one
with no lineage at all. D56's shape a third time, after `Chapter.primary_competency_id`
and `Student.home_class_id` (D69).

**Every source gets D61's ownership check, not just the principal.** D61 closed the hole
on a single `source_sheet_id`; a list reopens it at position 2, and a colleague's sheet
title reaching a printed feedback page is the exact failure D61 exists to prevent.

`AdaptiveBatchRequest` keeps `source_sheet_id` alongside the new `source_sheet_ids`, and
`resolved_source_ids()` folds the two — an older client keeps working, and a caller that
sends both gets one de-duplicated lineage with the principal first.

**Rejected:** the table alone, without the column. Targeting, the feedback page and the
chapter fallback each need exactly one answer, and "the row at position 0" is a worse way
to ask than a foreign key — it demotes a constraint to a convention.

**Not done here:** targeting still reads the principal only. D63 builds gaps from one
corrected sheet and that is unchanged; the set records what the teacher says the batch
answers.

### D71 · A sheet's Competences and Themes are derived, not stored

The obvious schema is `sheet_competency` and `sheet_chapter` join tables. Rejected: they
would have to be rewritten on every item edit, and between the edit and the rewrite —
or after any path that forgets — they describe a sheet that no longer exists. Two
answers to "what does this sheet cover?", one of them stale, is worse than one answer
that costs a join.

`SheetItem -> Exercise -> exercise_competency` already holds it, and
`exercise_competency` is a real many-to-many that the mastery model already reads. So
`sheet_service.sheet_coverage` derives both sets and `SheetOut` carries them as
`competency_ids` / `chapter_ids`.

`Sheet.chapter_id` is untouched and stays the sheet's single home Theme (D60,
I-sheets-11). The two are deliberately different: the home is what the teacher **stated**
and what the tree files the sheet under; the coverage is what the items **reach**. A
sheet in `unfiled` still covers whatever its exercises cover, and inferring a filing from
the second would be exactly the guess-promoted-to-a-fact D60 refuses.

An item no one tagged contributes nothing rather than a guessed Theme — `Exercise.chapter_id`
is itself an inference and null on a large minority of a real textbook.

### D72 · A sheet gets a band, and it is a roll-up, not a mean

`MasterySnapshot` answers "how is this child doing on X"; the tree answers it for a
Theme, a Competence and a Branch. Nothing answered "how did this child do on **this
sheet**" without leaving the five bands for a percentage — which is what the original
brief asked for, and what would have put a second scoring rule in a product whose whole
claim is that a band means one thing everywhere.

`mastery_service.sheet_mastery` is the existing arithmetic at a new altitude: attempts
bucketed **per competency**, each bucket scored by `compute_mastery`, and only then
combined by `roll_up_mastery`. The grouping is the invariant — a mean over raw item
correctness derives one recency from a mixture, which is I-mastery-10 broken one level
up. `sheet_mastery_overall` pools across **students** through the existing
`pool_by_competency`, which is the combination the model does allow.

Every competency the sheet covers is a child, including those with no evidence.
`compute_mastery([])` is the NONE band: it weighs nothing in the roll-up (I-mastery-09)
but counts toward `child_count`, so the coverage a teacher reads is honest rather than
being silently about the two competencies that happened to be examined (DC-content-07).

**Adaptive-sheet mastery is the same function.** `Sheet.target` never enters the
arithmetic, so "adaptive sheet mastery" needed no second implementation that could drift
from the first.

**Computed, not stored.** No `SheetMastery` table, for the reason `api/v1/mastery.py`
already gives about the matrix: the score decays with time, so a sheet opened on Friday
must not show Monday's numbers.

### D73 · A teacher is assigned a branch in a class, and ownership is a union

`class.teacher_id` carried two facts that only looked like one while a class had a single
teacher: **who may read this class** and **who is its maître de classe**. Mme Martin takes
French *and* maths in 5A while M. Lambert takes history in the same 5A, and none of that was
expressible — the schema could say "Martin owns 5A" and, separately, "5A studies French and
maths", which is indistinguishable from "Martin owns 5A and teaches everything in it".

Split the way D56 split `Chapter` and D69 split `Student`: where a row *sits* is a column,
what it *belongs to* is a join table. `class.head_teacher_id` is the maître de classe;
`class_teacher_subject` is who teaches which branch here.

**`class_subject` stays.** It is what the class STUDIES and it carries the Branch nav order,
one value per (class, subject); `class_teacher_subject` is who TEACHES it. Moving `position`
into a table grained by teacher would leave two co-teachers' rows for one branch with nothing
forcing their order to agree — a nav that depends on who is looking. And deriving the branch
list from staffing is D57's circularity in a new costume: a Branch would vanish the moment
its teacher was unassigned, taking its Themes, sheets and bands with it. The composite FK
makes `class_subject` provably the superset.

**Ownership is a union, not a lookup.** Head teacher **or** any assignment. The head-teacher
arm is not decoration: it is what keeps a class with no declared branches visible to its own
teacher, and it is what makes the 0021 backfill provably behaviour-preserving — afterwards
every class's assignment set is exactly {head teacher} × {declared branches}, so the union
selects exactly what the old single predicate did. `test_migration_0021.py` asserts that
rather than trusting it.

**Two grains, and the names carry which is which.** `owned_*` is class-grained — may I know
this class and these children exist. `taught_*` is pair-grained — may I see this teaching
artefact and this evidence. *Who you may name is class-grained; what you may see about them
is pair-grained.* The new failure mode is the mirror of the old one: a laxer rule leaks a
roster, a **stricter** rule invented in a new read path locks a co-teacher out of the class
they teach.

**Rejected: narrowing the roster and the student profile by branch.** A co-teacher already
knows who is in the room, and `_owned_student` is D69's widening — narrowed by subject, a
child the history teacher actually teaches would 404 for them. `Attempt` also reaches subject
only through `Exercise`, so it would mean a subject predicate across the whole mastery module
to produce a partial child. Revisit if a school ever asks for a confidentiality wall between
colleagues; it is then a policy flag over one predicate, not a schema change.

**Both columns renamed, not kept.** D69's reasoning: there were five read sites to judge one
at a time as "ownership" or "the class's own teacher", and under the old name every site
nobody reviewed would have gone on compiling with the old meaning.
`mastery_service._owned_student` is this change's `scan_processing.wrong_class`.

`class_teacher_subject.teacher_id` is **RESTRICT**, not the module's usual CASCADE: deleting
an account must not strip a class of its last owner and leave a roster of named children
nobody can open. No `ended_at` — unassigning is a deleted row (D69's rejected alternative).

**Also rejected: the ~12 stored `*Mastery` tables** the incoming spec asked for, and
`points_earned` driving mastery. The score decays, so a stored 78% is wrong the next morning
(D72 already refused a `SheetMastery` table for this); and `Attempt.score` is the teacher's
barème while `Attempt.correct` is what the model reads — a marking scheme must not rewrite
what the model believes a child knows.

### D74 · One teacher, several staffrooms; the tenant comes from the session

`teacher.school_id` was the tenant boundary every query filters on. A teacher who splits
their load between two establishments belongs to both, so the fact moved to `teacher_school`
and the column that stayed — `home_school_id` — answers where the account is based and which
school `login` mints the first cookie for.

**The session already carried it.** `core/security.py` has serialised
`{"t": teacher_id, "s": school_id}` since 0001, and `SessionData.school_id` already existed;
`get_tenant` simply ignored it and returned the teacher's row instead. So this is not an auth
reshape. `get_membership` resolves the teacher and the school together — they are one
question, *is this cookie still entitled to this tenant* — and every other dependency derives
from it, so the entitlement is answered once per request and in one place.

The membership check is a **`SELECT`**, deliberately, not `session.school_id in
teacher.schools`: a relationship read can be answered from a stale identity map, and this is
the single line standing between a cookie and another school's roster.

**No live session is logged out by the deploy.** The backfill gives every teacher exactly the
school their cookie already names, so `session.school_id` still resolves to what
`teacher.school_id` used to return. `SESSION_SALT` is deliberately not bumped for the same
reason: the payload is byte-identical and its meaning is a strict widening.

`Teacher` therefore leaves `SchoolScopedMixin` and becomes the **second** documented
exception to I-platform-02, after the curriculum (D11). That is honest rather than
regrettable: a row carrying one `school_id` is a row belonging to one tenant, which a teacher
working at two no longer does. `uq_teacher_email` stays global — one human, one account,
several schools; a per-school email would mean two password hashes for one person and would
make `login`, which looks up by email alone, ambiguous. `uq_student_uid` is unaffected:
`SchoolYear` is itself school-scoped, so two schools hold distinct year rows and therefore
distinct UID namespaces.

**Rejected: dropping `home_school_id` entirely.** Purer by §2's own test — once the tenant
comes from the session, nothing needs exactly one answer — but it takes `Teacher` out of the
mixin *and* leaves `login` with no default school to mint a cookie for.

### D75 · A teacher sees only what they teach, and the branch endpoints ship

D73 made ownership assignment-based. This is the half a teacher can see: reads narrow to the
branches they take, and there are finally endpoints for saying who takes what — the feature
D57 named and deferred as "a real feature with its own review".

**Pair-grained, wherever a branch exists.** `sheet_service.get_sheet` and `list_sheets`,
`scan_service._owned_scan`, `class_service._pending_scan_counts` and `_last_sheets`, and the
agenda all filter through `taught_here`. A colleague sharing a class is not a colleague
sharing a subject, and before this a maths teacher's sheet list, grading queue and home card
were a mixture of their own work and somebody else's.

**Two carve-outs, both because a branch does not exist there even in principle.** The roster
is names and UIDs, which a co-teacher already knows by standing in the room — and narrowing
it would mean the history teacher cannot take a register. An **unmatched pile** has no
subject at all, so it stays with the person holding the paper. That second one was the
argument that nearly sank strict isolation: a pile that gained a subject later would change
visibility mid-workflow. It cannot, and the fix is structural rather than a special case —
the sheet is attached through the now pair-grained `get_sheet`, so a teacher can only ever
attach a sheet they already teach.

**Rejected: narrowing the student profile.** Kept whole, deliberately. `_owned_student` is
D69's widening, and a maths teacher noticing a child sinking across every branch is a feature
of this product. See D73's rejected alternatives.

**The agenda needed three cases, not two.** Events with no class stay staffroom-wide (D23);
class-level events with no branch — the class was created, a roster pasted — stay visible to
anyone with a footing; everything else is pair-grained. `event_service.list_events` takes the
predicate rather than building it, because tenancy predicates live in `services.enrollment`
and a read path that invents its own is how the rule drifts.

**`ClassOut.subject_ids` now means "mine here", and the class's own list moved to
`declared_subject_ids`.** Two facts, two fields. Redefining the one field would have made the
Branch nav silently per-viewer; leaving it as the class's would render branches the reader
cannot open.

**`declare_subject` writes both facts.** A teacher who built a sheet in a branch nobody had
recorded them teaching would lose it immediately — not in their tree, not in their list. That
is D57's own argument for `declare_subject` applied one level down, and it is what keeps the
table populated with no new step for the teacher.

**Any owner may assign a colleague**, matching `enroll`. A head-teacher-only rule is one
`if`, but every ownership failure here is a 404 and this would be the first 403. It is the
same question as who may rename a school and who may delete a chapter, and it deserves
deciding once — a `role` column on `teacher_school` — rather than three times.

**`undeclare_subject` refuses with a count while sheets exist**, the same shape as `unenroll`
refusing on the home class. Removing a branch from a settings screen is not a teacher saying
"throw away the term's worksheets". **Reordering takes the whole list** and keeps branches the
caller did not name, because the order is the class's: a partial update from one co-teacher
must not renumber another's.

### D76 · The teacher edits their own school's nouns, and the curriculum stays read-only

The write surface was create-only: no `PATCH` or `DELETE` existed anywhere for `Class`,
`Student`, `Subject`, `Chapter`, `School` or `Source`. Everything below is about what the
new endpoints **refuse**, because a create endpoint makes reachable what a curated seed
never produced.

**`uq_subject_key` is a prerequisite, not a tidy-up.** `Competency.subject_key` matches
`Subject.key` by *string*, so two subjects keyed `mathematics` in one school split the
curriculum silently — half the competencies resolving to each, no error anywhere. The
constraint had never mattered because subjects only came from the seed. 0022 also refuses
to run against a school that already holds duplicates rather than merging them: moving
sheets, chapters and exercises between two subjects is not a migration's decision.

**Renaming is not re-identifying.** A label always. A `key`, a `code` or a `uid` never,
once paper has been printed from it. So: `Subject.key` is absent from `SubjectUpdate`
(the curriculum joins on it); `Student.uid` and `number` are absent from `StudentUpdate`
(I-platform-09); and `Class.code` is editable **only while the class has no pupils** —
before a roster exists it has minted no UIDs, and a typo made at creation must be fixable.

**`School.default_curriculum` is not editable at all.** It is resolved once, at seed time,
into every `Chapter.primary_competency_id` (D56). Changing it later leaves every Theme
hanging from the other curriculum's node — a silent mis-filing of the whole tree, from a
settings field that looks like a preference.

**"Add a competence I teach" is not curriculum CRUD.** A `Competency` is national
reference data shared by every school (D11); a teacher cannot create or delete one. What
they choose is which competencies their Theme *credits* — the `chapter_competency` m2m,
edited through `PATCH /chapters`. **Rejected: a per-assignment competency selection
table.** It is a fourth grain, it duplicates what `chapter_competency` already says, and
it must be maintained by hand for the matrix to stay honest — a stale selection hides a
competency the child was actually assessed on, which is worse than no selection.

**Deleting a Student is the only operation allowed to destroy evidence**
(`data-model.md` §6), and it takes the pupil's **UID typed back**, not a boolean: a caller
firing `?confirm=true` at the wrong row deletes the wrong child. It is restricted to the
**head teacher of the home class** — a co-teacher reads the pupil, because D73 is
deliberately class-grained about identity, and that must not extend to erasing another
teacher's pupil. The first implementation gated on `get_class` and got this wrong; the
test written for it is what caught it.

**Every other delete refuses with a count.** A Theme holding sheets, a textbook whose
exercises still cite it. `Sheet.chapter_id` is RESTRICT so the Theme refusal existed
anyway — as an unreadable 500. `Exercise.source_id` is SET NULL, so the textbook delete
would have *succeeded* and quietly stripped provenance from every exercise cut from the
book, which is the one thing `ExerciseOrigin.TEXTBOOK` exists to assert. The stored PDF is
left in place: `Storage` has no `delete`, and an ordinary button is not where to introduce
an untested destructive call on the object store.

**A single-student add needs no endpoint.** `POST /classes/{id}/students` already takes a
list with `min_length=1`. A second write path would duplicate the uid/number arithmetic —
the one piece of arithmetic in this codebase that gets printed on paper.

### D77 · The corpus is shared for reading, not for deleting

D11 and I-platform-04 share subjects, chapters, textbooks and exercises across the
staffroom on purpose: a colleague's scan of a textbook is meant to be usable, and every
read of it is school-wide.

Deleting is not reading. `delete_chapter` and `delete_source` refuse a caller who does not
hold that branch in any class of this school (`taught_subject_ids_anywhere`). It is the
one place strict isolation (D75) reaches into the shared corpus, and only because the
write destroys something.

**Deliberately narrow.** Reads are untouched — a teacher who does not take German still
lists German chapters, which is what makes the staffroom a staffroom. And it needs no new
schema, which matters because the honest long-term answer is a `role` column on
`teacher_school`: that is the same question as who may assign a colleague to a branch
(D75) and who may rename the school (D76), and it deserves one decision rather than three.
Until then, "you teach it" is the narrowest defensible rule that already exists in data.

### D78 · The branch curve is a cache, and a separate table

A Branch-level history needs stored points: the score decays, so yesterday's number cannot be
derived from today's attempts. History is the one question recomputation cannot answer, and it
is the only reason this table exists.

**A nullable `competency_id` on `MasterySnapshot` was rejected.** It would turn every
`(student, competency)` key in `latest_snapshots` into an optional and let I-mastery-07's "one
row per student, competency, day" silently admit two kinds of row. `mastery_branch_snapshot`
is its own table, with its own unit-interval check.

**Nothing reads it to answer a band.** Every read path recomputes (`data-model.md` §4), which
is what D72 already established when it refused a `SheetMastery` table.
`test_no_read_path_answers_a_band_from_the_cache` poisons the cache with a perfect score for a
failing child and asserts the tree ignores it — the contract is tested, not merely documented.

It is rolled up with `roll_up_mastery` over the same `MasteryResult`s the tree uses, never by
pooling raw attempts across competencies: that would derive one recency from a mixture, so a
competency practised last week would launder the staleness of one last touched in June
(I-mastery-10). It stores `child_count` and `assessed_child_count` beside the score, because a
band over one assessed competency and one over three are different claims, and a cached number
that dropped the denominator is exactly the dishonesty DC-content-07 forbids on screen.

**The branch is resolved through `exercise_competency` → `Exercise.subject_id`, not through
`chapter_competency`.** A competency is assessed by *exercises*, and an exercise always has a
subject; a Theme crediting that competency may simply not exist yet. Resolving through chapters
left every curve empty until somebody had filed a Theme — D57's circularity in a third costume,
and a failing test is what found it. It is also the more faithful edge: `exercise_competency` is
what mastery itself reads through, so the curve groups by the same relation that produced the
numbers.

### D79 · A second school is created from the product, and joining it is not switching to it

`POST /schools` creates an establishment and makes the creator a member in the same breath — a
school nobody can act for is not a school, and `get_membership` would refuse the very next
request. It deliberately does **not** move the session: creating a school and acting for it are
two decisions, and doing both at once would move the tenant out from under a teacher who was
only setting things up. `POST /auth/school/{id}` is the deliberate move (D74).

`default_curriculum` is settable here and nowhere else. It is resolved into every
`Chapter.primary_competency_id` the moment the school gets chapters (D56), so the one safe time
to choose it is before any exist.

Adding a colleague is gated on the **caller's** membership, and a school they do not work at
reads as missing — so the endpoint cannot be used to discover which school ids are real.


### D80 · The teaching screen, and the refusal it has to be able to say out loud

D75 shipped the endpoints for who teaches what. This is the screen, and three decisions came
out of building it rather than out of planning it.

**`undeclare_subject` gets its own error code, `branch_holds_sheets`.** `api/errors.py` already
says a conflict the teacher can resolve — and each is resolved differently — deserves a name
rather than sharing the generic one. This one is resolved by moving the sheets, and the count
is the whole message: the catalogue's generic `conflict` sentence ("cette action n'est plus
possible dans l'état actuel") names nothing and suggests nothing. The count reaches the screen
in `details.sheet_count`, which the API was already sending and nothing could read.

**The count is told in the dialog, after the attempt, and the confirm then goes cold.** It
cannot be shown on the branch panel: the API returns it on the refusal and `ClassOut` does not
carry it, and a number invented client-side would be a promise the read path cannot keep. Going
cold is specific to *this* refusal — pressing again cannot get past it until the sheets move,
whereas a network blip is worth another press and leaves the button live.

**The screen reads `declared_subject_ids`, and it is the only one that does.** Everywhere else
narrows to the reader's own branches, which is the whole point of strict isolation. Here the
superset IS the subject matter: a branch on the class's programme that nobody teaches is a real
state, and this is the only place it can be seen or repaired. A branch still gets no colour,
icon or tint — the mandarin means "a model wrote this" and nothing else (DC-colour-06), so a
branch is named (DC-colour-08) and the head teacher is marked with a written label, never a
violet pill (DC-colour-05).

**Two defects the canvas-vs-browser comparison caught, both fixed at the shared level.**
`ConfirmDestructive` rendered `error` only inside its typed-confirmation `Field`, so on a dialog
without one the message had nowhere to go — the server's refusal went silently missing. And a
disabled **ghost** button inherited the shared `:disabled` face (`--c-surface-2`) plus a drop,
which on an edge-less button reads as a small grey box that appeared out of nowhere; an
end-of-list reorder arrow looked broken rather than merely out of moves. Ghost now keeps its
own nature when disabled, and ink alone carries the state.

**The reorder arrows sit side by side, not stacked.** A stacked pair fits the panel header in
44 px total and gives each arrow 22 — half the floor this product holds itself to, on a screen
used on a phone. Two full-size targets spend width, which that row has, rather than height.


### D81 · The grading call arms the PII gate, and a pile with no class is not graded

`open_answer_grading.grade_one` called `ai.complete` without `student_names`, alone among the
call sites. `assert_no_pii` then ran only its email/phone/AHV regexes: the roster comparison —
the check that actually matters for this prompt — was skipped. What the prompt carries is
`SheetItem.statement_override` and `SheetItem.expected_answer`, free text a teacher typed, so
this was the call site most likely to receive a pupil's name by hand, and the one with no
positive control asserting otherwise.

**The roster is read once per pile, not once per box.** One scan is one sheet is one class;
`roster_names` runs a single query in `grade_open_answers` and every box reuses the answer.

**`roster` is a required keyword on `grade_one`, and `None` means "do not call".** `Scan.sheet_id`
is nullable and detaches on `ondelete="SET NULL"` — the same detachment that had
`assignable_students` offering the whole school — so a pile whose sheet was deleted has no class
to check a prompt against. `None` is not an empty roster: `[]` is a class with nothing to forbid, `None` is a gate
that cannot be armed. Sending anyway with the check off is the one option that is not available —
an exercise's own statement is no safer than the teacher's wording, because a textbook's Léa is
also in the class. The box settles `NOT_GRADEABLE`, which the teacher already sees and can
correct by hand, and rule 1 of the module (nothing stays `PENDING`) still holds. Making the
argument required rather than defaulting to `None` is what stops a future caller reintroducing
the disarmed call by omission.

**A blocked call is flushed to the audit log.** `flush_ai_log` ran only on the success path, so
the `ModelCall` row proving the gate fired was discarded with the exception — the one row an
auditor would ask for. It now runs in the `except` branch too; `flush` drains, so the success
path having already run makes the second call a no-op rather than a duplicate. No content is
written either way: the string that fired `PiiLeakError` is by definition the one carrying a name.

Not fixed here: `docs/privacy.md` names `apps/api/tests/ai/test_scrub_no_pii.py` as the normative
test parametrised over every call site. That file does not exist. The gate is tested per call
site instead, which is why a missing positive control could hide here for as long as it did.

### D82 · What a request queues is what it costs, and Chromium gets its own bucket

`POST /scans` carried no rate limit because its handler is cheap: it stores bytes and returns.
But `PROCESS_SCAN` chains `GRADE_OPEN_ANSWERS`, one provider call per written answer per copy,
so one unthrottled POST of a 28-copy pile with 6 open items is ~168 calls — more than any of the
endpoints that *were* limited. `POST /sources` was the same shape: a whole textbook through the
extraction prompts, started from a handler that only queues. **An endpoint is rate limited for
what its job chain reaches, not for what its handler executes.** Both now take `AiRateLimit`,
the same dependency as `/sheets/propose` and the adaptive routes.

**Rendering and preview get a second bucket, not the AI one.** `/sheets/{id}/render`,
`/adaptive/batch/{id}/render` and both preview routes never reach a provider — they spawn
headless Chromium, or paginate synchronously inside the request handler. Spending a teacher's
AI budget on a preview would mean previewing a draft costs them a generation, which is the wrong
trade in a builder whose whole point is that previewing is free. `RenderRateLimit` is the same
`TokenBucketLimiter` against a separate setting, `render_rate_limit_per_min`, defaulting to 12:
lower than the AI bucket because the cost is a process on the API box rather than a line on the
provider bill, and a teacher reprinting legitimately does it a few times, not twenty.

**The ceiling is per process, and the setting has to be read that way.** `TokenBucketLimiter`
holds its buckets in memory, deliberately (it guards against a held click, not against spend).
With N uvicorn workers a teacher's real ceiling is `rate_per_min × N` — 4 workers and the default
20/min admit 80/min. Both dependencies say so where the number is chosen, and `.env.example`
repeats it, because the trap is reading `ALPPY_AI_RATE_LIMIT_PER_MIN=20` as a global 20. The hard
cost ceiling stays where it was: `ai_max_output_tokens` and the provider account.

### D83 · A pile has a count limit, and it is checked before the first read

`POST /scans` takes `files: list[UploadFile]`, and `read_upload` bounds each one at
`ALPPY_MAX_UPLOAD_MB` — but nothing bounded how many. Every payload is bytes held for the life of
the request (`UploadPayload` is documented as "held in memory, never a path", because the scan
job wants the bytes, not a temp file), so the list comprehension in the handler materialises the
whole pile at once: 200 files at the 50 MB cap is 10 GB through one API process. The only
existing check was `create_scan` refusing an *empty* list, and that runs after everything is read.

`ALPPY_MAX_UPLOAD_FILES` defaults to **120**, enforced by `deps.check_upload_count` ahead of the
first `await` — after that point the bytes are already buffered and refusing costs the same as
accepting. 120 is a real pile, not a guess: the workflow is photographing a class set page by
page, and 30 copies of a four-page sheet is 120 files. A 413 (`payload_too_large`, with
`max_files` and `received` in the details) rather than a 422: it is the same class of refusal as
the per-file cap, and the client shows it the same way.

**The count is a bound, not the bound.** Worst case is still
`max_upload_files × max_upload_mb`; a deployment on a small box lowers one or the other, and both
the setting's docstring and `.env.example` say so rather than leaving the multiplication to be
rediscovered.

### D84 · Tenancy stops being only the application's promise

Every tenant-scoped query carried its own `.where(school_id == ...)`. Services took `school_id`
as a required argument so a handler that forgot it failed to type-check, and `deps.scoped_get`
was the one blessed way to fetch a row by id. That design stays and is still the first line —
but underneath it there was nothing, and one missed `.where()` was an unbounded cross-school
read. The API, the worker and Alembic also shared a single DSN naming the database owner, so a
SQL-injection or a bug in a raw query had the whole cluster, and nothing bounded a runaway
statement.

**Row-level security on every school-scoped table, keyed on a GUC the request sets.**
`app.current_school_id`, set with `set_config(..., is_local => true)` — transaction-scoped, so it
cannot outlive the request and be inherited by the next checkout of the same pooled connection.
`alppy/db/tenancy.py` is its only writer. Because a service commits several times on the way
through a request, it is re-applied on an `after_begin` listener rather than once per request;
binding once would leave everything after the first commit reading with the GUC unset.

**Unset means see nothing.** The predicate is
`school_id = nullif(current_setting('app.current_school_id', true), '')::uuid`. Never-set and
set-to-empty both collapse to NULL, and a comparison to NULL admits no rows. A bare cast would
have raised on the empty string — an error page where an empty list belongs — and a policy that
defaulted to permissive would make every unbound code path a leak rather than a blank screen.
`WITH CHECK` carries the same predicate as `USING`, so writing *into* another school is refused
as firmly as reading out of one.

**The tenant is bound in `get_membership`, and nowhere else.** Not in `get_db`: at the moment a
request's session opens, nobody knows the school yet, because resolving it means reading
`teacher_school` — which needs a session. So the session starts blind and is bound the moment
that check answers, in the one place the entitlement already lives (I-platform-14). A handler
taking `DbDep` without `TenantDep` or `ScopeDep` therefore never gets bound and sees nothing.
That is the intended behaviour: the failure mode of a forgotten tenant is now an empty result.

**`FORCE`, and two roles, because either alone is decoration.** Postgres does not apply a policy
to the role that owns the table, and `FORCE` extends it to the owner — which is who Alembic and
the CLI connect as. The API and worker connect as `alppy_app`: no DDL, no `BYPASSRLS`, DML only.
Both halves are load-bearing and the failure is silent in both directions, so
`Settings._refuse_unsafe_deployment` refuses a staging or production boot where
`ALPPY_ADMIN_DATABASE_URL` is unset or names the same role as `ALPPY_DATABASE_URL`. A deployment
with every policy in place and none of them firing looks exactly like a working one.

**The six association tables get EXISTS policies, not a `school_id` column.** `class_student`,
`class_subject`, `class_teacher_subject`, `chapter_competency`, `exercise_competency` and
`sheet_source` deliberately carry no `school_id`: the models argue both ends already do and
tenancy holds transitively (I-platform-02). A policy is where that argument becomes enforceable,
so each is written as an EXISTS against the parent that has the column. Adding the column would
have contradicted the models' own reasoning and put six redundant, backfilled, drift-prone
copies of a fact into the schema to save a primary-key lookup. The EXISTS names the parent's
`school_id` explicitly rather than leaning on the parent's own policy to filter the subquery —
that shorter form works, but for a reason the reader has to already know, and it breaks the day
someone exempts the parent.

**`school` is the one table a request reads across the boundary, so its policy says so.** Since
D74 a teacher may work at several schools, and login, `/auth/me` and `POST /auth/school/{id}`
all list or open one the current GUC does not name. Its policy admits the current school OR any
school this teacher is a member of — the same question `get_membership` asks, asked again one
layer down, which is why `app.current_teacher_id` exists as a second GUC. Without the second arm,
switching school would 404 every school including the one being left. `teacher` and
`teacher_school` stay uncovered: both are read *before* any tenant is known, during login, and a
teacher is not a tenant-scoped object. `competency` stays uncovered because the cantonal
curriculum is shared reference data.

**The worker's chicken-and-egg gets one uuid of escalation.** The tenant is on the `Job` row the
worker has not been allowed to read yet. Widening the worker's role would have given the
sensitive half of the pipeline a blanket exemption; putting the school in the arq payload would
have left every job in flight across a deploy arriving without one. Instead `alppy_job_school` is
a `SECURITY DEFINER` function taking a job id and returning a school id, which can say nothing
else — content-free in the same sense `ModelCall` is. Its `search_path` is pinned, because a
`SECURITY DEFINER` function resolving a table through a caller-controlled `search_path` is a
privilege escalation with a CVE number waiting.

**The cross-school CLI is the deliberate hole, and it is visible.** `seed`, `backfill-events` and
`purge-prompt-logs` sweep every school by definition, and no value of the GUC means "all of
them". They open `admin_session()` — a separate factory, a separate DSN, a separate name — so
reaching for the exemption is an act rather than a flag.

**`statement_timeout` on the role, raised per process.** A connection string is edited by whoever
is debugging a timeout; the bound that protects the database is the one they cannot drop by
accident, so 15s and a 30s `idle_in_transaction_session_timeout` sit on `alppy_app` in
`init.sql`. `ALPPY_DB_STATEMENT_TIMEOUT_MS` is the per-connection override above it, and the
worker raises its own to 120s rather than the API lowering its guard to fit a scan pipeline.

**None of this is testable by the unit suite, and that is why it has a CI job.** The suite builds
its schema with `create_all()` on SQLite, which has no roles, no `set_config` and no row-level
security — the same structural blind spot `check-schema-drift.py` exists for.
`scripts/check-rls.py` migrates a disposable Postgres, creates a low-privilege role, and asks the
questions that matter behaviourally: with the GUC unset, is anything visible; bound to school A,
is B's roster reachable through `student`, through `class`, through `class_student`; does an
INSERT or an UPDATE naming B succeed; can the runtime role run DDL or turn RLS off; does it hold
`BYPASSRLS`. It also fails on any `SchoolScopedMixin` table with no policy, which is what keeps a
table added next year covered.

### D85 · The staffroom is flat on purpose, and the admin tier has a named shape

Four write endpoints take no privilege check beyond membership: `POST /schools`
(any teacher may create an establishment and joins it), `POST
/schools/{id}/teachers/{id}` (any member may add any teacher to a staffroom they
work in), `PATCH /schools/me` (any member may rename the school), and the
destructive corpus writes, which check *teaching* rather than rank
(`_assert_teaches_subject`, D77). D77 named the missing tier and deferred it —
"the honest long-term answer is a `role` column on `teacher_school` … it deserves
one decision rather than three." This is that decision, and the answer for now is
**no roles**, recorded so it stops reading like an oversight every time someone
audits the module.

**Why flat is right for the institution we are actually in.** A Swiss Sek I
établissement is ten to sixty teachers who know each other by name and share a
staffroom in the physical sense. The directeur is a colleague with a timetable,
not a systems administrator, and nobody in the building holds a support rota. An
admin tier in that setting does not prevent the actions above; it decides *which
colleague has to be found* before an ordinary Tuesday can continue — and the
predictable end state is that the first account becomes admin, that person leaves,
and the school files a support ticket to rename itself. Every action on the list is
also reversible in place (a rename, a membership) or already guarded by something
better than rank: `delete_source` refuses while exercises cite the book,
`delete_chapter` while it holds sheets, `delete_student` demands the pupil's UID
typed back. What a role column would add to those is a second, weaker lock on a
door that already has one.

**What is genuinely load-bearing is the tenant boundary, and it is not this.** The
question "may this session act for this school at all" is answered by
`get_membership` and, since D84, again by row-level security underneath it. Every
endpoint here sits *inside* an answered boundary: none of them reads or writes
another school's data, and `add_teacher_to_school` is already gated on the
caller's own membership so a school you do not work at reads as missing rather
than as forbidden — which is why it cannot be used to enumerate school ids. The
exposure of a flat staffroom is a colleague doing something clumsy to shared
state, not a stranger reaching across a tenant.

**Two things that are not privilege questions and should be fixed regardless.**
Neither needs a role column, and neither should wait for one:

* **Membership is add-only.** There is no `DELETE
  /schools/{id}/teachers/{id}`, so a teacher added by a mistyped uuid cannot be
  removed except by hand in SQL. `teacher_school` was designed for this —
  leaving a school is a deleted row (no `left_at`) — so the endpoint is missing,
  not blocked.
* **`POST /schools` is unbounded.** Nothing rate-limits establishment creation
  or caps how many one account may hold. It creates an empty school and reaches
  no existing data, so it is a housekeeping concern rather than a security one,
  but it is the one action on the list that a script could repeat.

**The minimal shape if a school asks for the tier.** Not a `Role` table and not a
permissions matrix: **one boolean column, `is_admin`, on `teacher_school`**, which
is the table that already carries the relationship the flag qualifies. A `role`
enum was the phrasing in D77 and is the worse of the two — three names invite a
fourth, and every one of them needs a matrix nobody has asked for. The migration
sets it true for the earliest `joined_at` per school, which is the person who set
the school up. Enforcement is a dependency beside `TenantDep` (`AdminDep`, reading
the same membership row `get_membership` has already loaded, so it costs no
query), applied to exactly the four endpoints above and to nothing else — in
particular **not** to the corpus deletes, whose "you teach this branch" rule is a
better question than rank and should survive the change. The invariant that must
come with it: **a school always has at least one admin**, enforced where
membership is removed, or the tier's failure mode is a school nobody can
administer — strictly worse than the flat model it replaced.

**Revisit if** a school runs more than one établissement under one account and
asks who may rename which; if a canton or a school's own IT policy requires a
named responsible party for the roster; or the first time a teacher removes a
colleague's textbook and someone asks who was allowed to.

### D86 · A failure reaches the teacher as a code, and the page carries a nonce

A frontend review asked five questions: what leaks in client code, what leaks in
error messages, where user content is rendered, whether a CSP exists, and
whether any screen over-fetches a roster. Two of the five were clean —
no key, id or secret is inlined (the only `NEXT_PUBLIC_*` values are the API
base and the mock and demo switches), and there is no XSS surface (two
`dangerouslySetInnerHTML` sites, both static; Jinja `autoescape=True` for the
print document, with `Markup()` only ever wrapping our own CSS; both preview
iframes sandboxed without `allow-scripts`). The other three are this decision.

**An exception's text is not a message.** `client.ts` already said `message` is
for the console, and three places ignored it. `Source.error` held
`f"{type(exc).__name__}: {exc}"` under a bare `except Exception` and the
/sources card printed it verbatim — a SQLAlchemy failure is the failing SQL and
its column names, an `OSError` is an absolute server path, a botocore failure is
the bucket and its endpoint, on a screen that spends a good deal of its life
projected onto a classroom wall. `Job.error` held `str(exc)`, uncapped in one of
the three writers, and `GET /jobs/{id}` is polled for the length of every
extraction. The sheet preview read `body.error.message` straight out of the
envelope.

So: **a failure crosses to the client as a code, and the client owns the
sentence.** `Source.error` holds prose written for a teacher, chosen by
`_teacher_facing_error` from a closed set. `Job.error` holds a value from
`services.job_failure.FAILURE_CODES`. Sheet render refusals get their own code,
`sheet_not_renderable`, so the teacher still learns *which* refusal it was
without reading English assembled for a log — `unprocessable` would have told
them the file could not be read, which is a different and untrue thing. The
diagnostics are not lost; they move to the log, with tracebacks.

Rejected: keeping the message and sanitising it. There is no predicate that
separates "a sentence someone wrote for a reader" from "the repr of whatever
was raised four frames down", and a sanitiser that gets it wrong fails open.

**The CSP is real, which costs the static shell.** There was none — nor
`nosniff`, `Referrer-Policy`, `X-Frame-Options` or `Permissions-Policy`, in
`next.config.ts`, the middleware, the API or anything in `infra/`. `Referer`
alone was carrying `/classes/…/students/<uuid>/…` to the object store on every
scan crop.

The policy is built per request in `middleware.ts` because it carries a nonce,
and the nonce reaches Next the only way Next reads one: through the request's
own `content-security-policy` header, which next-intl copies into its
`NextResponse.next({request})`. That works only while rendering — a prerendered
shell was built before any nonce existed, and **measurement, not assumption**:
the built page served twelve un-nonced `self.__next_f.push(...)` blocks, every
one of which a `script-src` without `'unsafe-inline'` refuses, so the page
would have arrived and never hydrated. Hence `dynamic = 'force-dynamic'` on the
locale layout. The shell was only ever prerendering a loading state — every
screen below it is a client component on react-query — so this costs close to
nothing, and it is the price of a policy that is not decorative.

`'unsafe-inline'` survives in `style-src` and only there: React writes
`style={{…}}` as an attribute, there is no nonce path for a style attribute, and
the alternative is not a stricter policy but a broken layout. The theme script
is allowed by **hash**, not nonce, so the layout does not have to read
`headers()` — with a test that recomputes the hash, because a stale one is a
flash of the wrong palette and a console error nobody reads.

**A count is not a roster.** The adaptive screen called `useStudents` and used
`.length` — pulling every child's first name, last name, uid and class codes to
render one slider bound, on the one screen whose whole design keeps names away
from a model. It reads `ClassOut.student_count`. Two other screens fetched the
roster beside a mastery matrix that already carries it in
`MasteryMatrixOut.students`; reading it from the one response also fixed a
flash where the roster arrived first and every pupil rendered at "0 assessed".

**Found on the way, and fixed:** five call sites handed `apiErrorMessage` the
`errors` namespace instead of `errors.code`, so the code lookup missed *and* the
fallback lookup missed — and next-intl's second throw escaped, crashing a screen
in the middle of reporting a handled failure. `apiErrorMessage` no longer
throws, and a test covers the empty catalogue.

**Revisit if** a deployment serves media from an origin that is not in
`ALPPY_MEDIA_ORIGINS` (scan crops render as empty frames, and the only
explanation is in the browser console); or if the sheet renderer grows refusals
that a teacher would act on differently, at which point `sheet_not_renderable`
should split rather than acquire a details blob.

---

### D87 · A membership ends, and a pupil outlives the year

A read-only audit of the data layer (`docs/audits/01-database-audit.md`) found
two Critical problems, and both were about time rather than about shape. Both
get more expensive every day the product runs, which is why they are fixed
before anything else on that list.

**Nothing recorded that a membership had ended.** `class_student`,
`class_teacher_subject` and `teacher_school` each carried a start and no end,
and leaving was a `DELETE`. The models said so and gave the reason — *"the
moment one exists every roster read grows a temporal predicate and every test
needs an injectable clock"* — and that cost is real. It was still the wrong
trade for Cycle 3, where pupils are streamed into maths niveaux *across*
homerooms and move between them mid-year. Léa sits three worksheets in the
niveau-2 group in October and moves to niveau 3 in February: one `DELETE`, and
she vanishes from the niveau-2 matrix *including the October columns she sat*,
M. Rossier 404s on the profile of a pupil he taught for six months and marked
three sheets for, and nothing anywhere says she was ever in that group. In
June, asked to justify her orientation to a parent, he cannot reconstruct the
group she was assessed in.

So the three tables grow `valid_from` / `valid_to`, the primary key widens to
carry `valid_from`, and leaving is an `UPDATE` (0027).

**Three things the audit did not ask for, and each is load-bearing.**

*A partial unique index per table.* Widening the key alone admits two OPEN
memberships for one pair with different `valid_from` — one child counted twice
in every roster join and every matrix column. `uq_class_student_open` and its
siblings are what keep "at most one current membership" true. They are also why
`enroll` is no longer `ON CONFLICT DO NOTHING`: keyed on the widened key, a
pupil unenrolled this morning and put back this afternoon collides on the
PRIMARY KEY, and `DO NOTHING` would drop the re-enrolment silently, leaving the
roster one child short with no error anywhere.

*`on` is a REQUIRED keyword argument on every subquery in
`services/enrollment.py`.* This is the safety mechanism, and it substitutes for
the rename 0019 and 0021 used. Adding the columns without it would have left a
dozen read sites compiling unchanged while the tables underneath them began
returning history — a roster quietly regaining the pupils who left, which is a
worse bug than the one being fixed. A required argument makes each of those
sites a type error the suite catches. The tables are NOT renamed to
`group_membership`/`group_staffing` (the audit's deltas 3 and 4): those names
presuppose a `teaching_group` entity, and 0026 chose `class.kind` over that
split, so the names would be a promise the schema does not keep.

*The gate for READING a pupil's past is overlap, not "ever".* `_owned_student`
now accepts a teacher whose staffing window INTERSECTED the pupil's membership
— which is what un-404s Léa's profile for M. Rossier. "Any pupil who was ever in
a class I was ever in" would hand a teacher who arrived in March a pupil who
left in October: two people who never shared a room, linked only by a group.
`class_service.get_student` deliberately keeps the CURRENT rule, because it
gates *acting* on a pupil — renaming, re-enrolling, deleting — and a teacher
whose group a child left in February has no standing to rename them in June.

**Two reads must not take an `on` at all, and they point opposite ways.**
`ever_enrolled_student_ids` feeds the PII scrub list, which has to be a
SUPERSET: a pupil who left in February still wrote their name on the October
copy in the pile, and a current-roster read would quietly stop scrubbing it — a
leak no test fails on, because the gate only raises for names it was told
about. `nouns_service.rename_class`'s guard counts pupils who were EVER seated,
because the class code is printed on paper that left with them.

**A pupil's identity did not survive the summer.** `student.school_year_id` is
NOT NULL and `uq_student_uid` is keyed on it, so 2027/28 needs a new `student`
row with a new UUID, and `attempt`, `mastery_snapshot`,
`mastery_branch_snapshot` and `misconception_note` all hung off `student.id`.
For a product whose mastery model is explicitly a decay model, that reset the
longitudinal record every August, over the one interval where decay matters
most: Noah repeats his 10e année and Alppy proposes him work as though he had
never seen the material he failed.

`person` is the durable identity — names, and `anonymised_at`, and nothing else
— and `student` is demoted to what it already was, a year-bound enrolment record
(0028). This is the third instance of a split this codebase has named twice
(D56 for `Chapter`, D69 for `Student`): *where a row sits is a column, what it
belongs to is a join*, applied to time.

The print and scan path stays on the year-bound row — `sheet_instance`,
`answer_box_placement.student_uid`, `scan_page.student_id`,
`exercise_variant.student_id` — because a UID is a fact about one year's paper
and must not change meaning.

**The columns are renamed, not repointed in place**, on 0019's argument: about
twenty read sites, and under the old name every one nobody reviewed would have
gone on compiling with the old meaning. **And the new ids are fresh, not copied
from `student.id`.** Reusing the uuid would have made the migration free — no
rewrite of the highest-volume table — and would have been a trap: every place
that confused a `student_id` with a `person_id` would keep resolving, silently
and correctly, until the first pupil had two `student` rows. Fresh uuids make
that confusion a foreign key violation on the day it is written.

**Erasure moves with the evidence.** Deleting a `Student` no longer destroys a
pupil's record — it cannot, or the record would vanish every August — so
`nouns_service.delete_student` deletes the person too, once no other year still
refers to them. Without that the endpoint would have gone on reporting success
while destroying nothing.

**Two more things this release does not do.** `class.kind` (0026) is a nullable
discriminator and nothing branches on it yet; NULL means "not declared" and is
NOT a synonym for `homeroom`, because every row predating it predates the
question. And `undeclare_subject`'s composite FK still CASCADE-deletes staffing
rows, which destroys the same fact 0027 exists to preserve — flagged rather than
changed, because altering a constraint is not a thing to do quietly.

**Revisit if** a rollover path ships (a person will then have several `student`
rows, and `_sheets_taken`, the profile and the adaptive planner will start
returning several years at once — which is the intent, but the screens have not
been designed for it); or if a teacher-facing "as of" control appears, at which
point the `on` already threaded through `enrollment` is the parameter it binds
to; or if `undeclare_subject`'s cascade is fixed, at which point ending the
staffing rows and dropping the `class_subject` row become two steps.

### D88 · A teacher who has left the group keeps what they marked, and may not act on it

D87 widened *who* a teacher may name — `ever_shared_student_ids` hands a
departed teacher the pupil profiles whose enrolment overlapped their own — and
stopped one join short of being usable. The sheets that profile links to were
still resolved through `get_sheet`, which gates on `taught_here(..., on=today())`.
So M. Rossier, asked in June to justify the orientation decision his eleven
niveau-2 sheets fed, could open Léa's profile and 404 on every piece of evidence
behind it.

`results_service.sheet_report` is where the two met and where the shape of the
mistake is clearest: it resolved the sheet through the current-only gate on one
line, then applied its own overlap-widened student lookup on the next — a lookup
whose comment describes the June case exactly, and which could not run in it.
That is what "two functions disagreeing about the same question" looks like once
it reaches a single call stack. The audit that found it counted it as one of
fifteen stale `on=` call sites; it is not, it is a policy that was never decided.

**Decided: reading is widened, acting is not.** `taught_here_ever` — the pair
predicate with the interval dropped — gates the six read paths (the sheet, its
preview, its mastery, its per-item confidence, its report, the notes already
written from it). Render, mark-printed, edit, batch-source resolution and
anything that bills a model call stay on `taught_here(..., on=today())`.

**"Ever", not "overlap", and the asymmetry with D87 is the point.** A pupil is a
person, so linking two people who never shared a room is a leak and the interval
intersection is what prevents it. A sheet is not a person: it is the teaching
material of a (class, branch), and a teacher taking that pair over in March
inheriting October's sheets is correct rather than merely tolerated — same
children, same branch. Where a sheet-grained read *names* a child, the student is
gated separately and still by overlap, and the two compose: Mme Dupont, arriving
in March, opens the October sheet and reads the report only for the pupils whose
time overlapped hers. Widening one did not widen the other.

**`list_sheets` deliberately stays current-only.** Browsing is the current
teacher's working surface; a group taken over in March must not open onto its
predecessor's back catalogue. A departed teacher reaches these sheets by
following a pupil's profile, which is the path the case is actually about.

`test_co_teaching.py::test_unassigning_takes_the_branch_away_without_touching_the_sheets`
asserted the 404 this reverses. Its load-bearing half — unassigning is not
deleting — is unchanged and now proves the stronger statement: the row survives,
its author still reads it, and what they lost is the ability to print into it.

**Revisit if** a school asks for a "left the school" state distinct from "left
this group" — `teacher_school.valid_to` already exists (0027) and is checked in
`get_membership`, so a departed *colleague* is already refused at the door
regardless of what this predicate says; but a school that wants a leaver's reads
cut off before their membership formally ends would need this gate to consult it.

---

### D89 · One door to paper, and the paper carries its own type

The Phase 4 frontend audit's two Critical findings are both on the printed
sheet, and they compound: F1, that there were two ways to print and only one of
them produced the coordinates the grading pipeline reads; F2, that the printed
document declared no `@font-face` at all, so each renderer typeset it in
whatever it happened to have.

**The browser-print path is gone rather than gated.** `Imprimer` called
`print()` on the preview iframe and then `POST /sheets/{id}/printed`. The
preview handler says of itself that it "renders the sheet's own stored rows and
writes nothing"; `AnswerBoxPlacement` — the rectangles `crop_answer_box` cuts a
written answer from — is written only by `render_sheet`. So a fiche with four
open items could be printed, sat by twenty-four pupils, photographed, and come
back with all ninety-six written answers `NOT_GRADEABLE`, counted as skipped,
with nothing anywhere connecting that to a button not pressed two days earlier.

It was offered as a fast path for bubble-only sheets, where the placements do
not matter. **Decided: it goes anyway.** The second half of the finding is that
even *with* placements the browser print is not the measured document — those
millimetres were measured in the API's Chromium at `@page { margin: 14mm }`,
while the paper comes off the teacher's browser at the printer's margins and
whatever "Fit to page" the school printer was left set to. Bubbles survive that,
because registration is fiducial-relative and a uniform scale cancels; answer
boxes do not, because they are stored as page millimetres. A fast path that is
correct for some sheets and silently wrong for others is a path a teacher has to
know the rule for. There is now one door: render, then print the PDF. The cost
is a worker round-trip on a bubble-only sheet, and it is worth it.

`lib/print.ts` is the gate. It reads **`rendered_at`** and nothing else, because
that field is already the server's own verdict: `update_sheet` nulls it —
together with both PDF keys — on any edit that changes the paper, a barème edit
included, "otherwise the teacher downloads a PDF whose (1 pt) disagrees with how
it will grade". A client-side `rendered_at < updated_at` comparison would have
been a second, weaker copy of a rule that already exists. And `markPrinted` now
fires only behind a link to a real PDF, so the agenda can no longer record a
print that produced paper nothing could grade.

**The faces travel inside the document.** `tokens.css` named four families and
nothing outside the Next bundle loaded any of them, because `@fontsource-variable`
is imported by the web app's layout and the print document is served by the API.
`scripts/embed-fonts.mjs` generates `packages/ui/src/design/fonts.css` — the
latin subset of each face as a `data:` URI, 242 KiB — and `html.py` inlines it as
a fifth stylesheet, first, with `fonts` in `DESIGN_CSS_SHEETS` so its absence is
fatal exactly as a missing `print.css` is. The output is committed because the
API image has no `node_modules`: `apps/api/Dockerfile` copies
`packages/ui/src/design/` and nothing else from the workspace.

This is measured, not assumed. An item is in normal flow, so its answer box sits
under a statement whose wrapping only the browser knows: with the faces stripped
and a different family substituted, a three-line statement becomes two and the
box moves **7.6 mm** — most of a written line, and comfortably inside
`_check_box_inside_statement_region`, which is why nothing ever raised.
`test_the_box_moves_when_the_font_stack_does` is that measurement. On a
developer's Mac the bug was invisible for a second reason worth recording:
Chromium resolved `'Nunito Variable'` to a *locally installed* Nunito, so the
fallback happened to be the right font there and nowhere else.

`_printed_page` now awaits `document.fonts.ready` before yielding. The PDF and
the measurement come from that one context, and its docstring already promised
"same media, same colour scheme, same fonts"; with real faces to load, that
promise needed a line of code behind it.

**`frame-src` names the API origin**, for the same reason `connect-src` already
did. Without it the preview was blocked in the compose default — and silently,
because the preview's error check is a `fetch`, which `connect-src` permits, so
the check passed while the frame stayed blank. The screen now also treats "the
frame never displayed anything" as a failure in its own right: a
`securitypolicyviolation` listener and a load timeout, rather than an empty A4
on a projector.

**Revisit if** the payload becomes a problem: Caveat is 73 KiB of the 180 and no
print template uses `--font-hand` today, so it is carried on the argument that
the *silent* failure is the one being fixed and a family named in the tokens but
missing from the document is exactly that. Dropping it is one line in
`PACKAGES`, and `test_tokens_still_name_four_families` is what would then need
to change with it.

### D90 · Work survives the tab, the session, and a bad photograph

Phase 4's four High findings about recoverability, taken together, because they
are one shape: something the app did silently discarded work or hid the true
state of a request.

**A differentiation run lives in the URL** (F4). The proposal was always durable
— `GET /adaptive/proposal/{job_id}`, with `staleTime: Infinity` because it costs
twenty-four provider calls to rebuild — but the id that addresses it lived in one
component's `useState`. Closing the laptop between **Proposer** and the result
lost a plan that was sitting finished in the database. It is now
`/adaptive?job={id}`, written with `replace` (a proposal is not a place in the
history), which is what the scan flow has always done.

`lib/adaptive-session.ts` holds the two things the URL cannot: the group moves,
and the ids of an export already started, keyed by job id in `sessionStorage`.
**Not `approvedIds`** — the line declaring it says approval is a fact about the
database and the export gate reads it, so restoring it from a tab's storage
could open that gate on nobody's authority. A recovered run therefore shows its
generated exercises as unapproved until the server says otherwise: one click to
put right, and the safe direction to be wrong in. Making it *true* on recovery
needs a read the API does not have — the stored proposal is a payload snapshot,
so the `approved_at` inside it is frozen at proposal time.

The recent-runs list is deliberately local. `GET /jobs?kind=propose_adaptive`
exists and has no caller, but it is scoped to the **school** and `JobOut` carries
no `class_id`, so a server-side list would tell a teacher that a colleague
started a run at 10:15 and could offer a row that 404s when opened. Reading the
ids out of this browser answers the case the finding is about. The gap, stated:
a run started on the classroom desktop is not listed on the laptop at home.
Closing it is one field.

**A 401 redirects** (F5). `docs/reviews/F7-review.md:178-196` offered two
directions on 2026-09-06 — a middleware guard, *or* a client boundary on
`isUnauthorized`. Only the first shipped, and it covers a visitor who is not
signed in, which is the other case. The one below is a teacher whose 12-hour
cookie expires mid-review: the cache still serves the pile, every verdict
answers 401, and `apiErrorMessage` says "L'envoi a échoué. Réessayez." Nothing
navigates, so the middleware never fires. `apiRequest` now dispatches to a
handler that clears the query cache and redirects — not on `/auth/me`, which is
the app *asking* whether a session exists, nor on `/auth/login`, where a 401 is
bad credentials and the login screen owns the sentence.

**Two boundaries, and a catch-all that makes one of them reachable** (F6). There
was no `error.tsx` or `not-found.tsx` at any level, while `notFound()` is called
and `errors.notFound.*` had been translated three times for nobody. Two things
were learned building it. First: an unmatched path never enters the `[locale]`
segment at all — Next 404s at the root, outside the intl provider — so a German
teacher typing `/de/klassn` got a French page. `[locale]/[...rest]/page.tsx`
claims the path so the miss is raised *inside* the layout. Second, and measured:
the root boundaries render outside the `force-dynamic` locale layout, so their
`__next_f.push` blocks carried no CSP nonce, `script-src` refused them, and the
browser showed an **empty body** where the server had sent "Page introuvable" —
`curl` returned the heading and Playwright saw nothing. `dynamic` on the root
layout, for the reason D86 gives for the locale layout. The status stays 200: a
`notFound()` inside a streamed dynamic render lands after the shell has gone
out. That is Next's behaviour, recorded rather than papered over.

**A retake joins its own pile** (F11). An unregistered page carried advice —
"reprenez la photo" — and nowhere to act on it; `/scans/new` makes a second pile
with its own review and its own confirmation. `POST /scans/{id}/pages` appends,
and this is the part worth writing down: **nothing deletes the pages already
read**, because the teacher's corrections hang off those rows. So the job
carries `from_file` and processes only what arrived. Two things had to move with
it. The per-UID `seen` counter is seeded from the rows already written — starting
from zero would place a re-shot page 2 into slot 0 and read it against page 1's
option counts, which is B5's misgrading arriving by another door. And the loop's
index is both `page_index` and the storage key (`page-003.png`), so a partial
run that restarted at zero would collide with existing rows and overwrite their
registered images in the bucket. `supersedes_page_id` discards the photograph
being replaced in the same transaction, so a copy is never briefly longer than
it was printed.

The model already expected this: `ScanPage.discarded` is documented as "a cover
sheet, a lens-cap frame, **a page re-shot later**", and `_place_page` says that
discarding the blurred original is what makes an overflowed pile ordinary again.
The route is what was missing, not the idea.

### D91 · The word "groupe" belongs to the class, not to the cohort

In Cycle 3 a "class" often *is* a teaching group — `10-MAT-N2`, the niveau-2
maths group — and Alppy was already spending the word on something else: the
adaptive differentiation cohort, seven times in the catalogue and once on the
printed page. One word for two containers, with the product's own worked example
unable to use it.

**Decided: `série`** (de `Serie`, en `set`). `lot` was taken and load-bearing —
the exported batch, and a scan pile ("Remettre dans le lot") — and `niveau`
collides with an exercise's difficulty ("Niveau 3 sur 5"). `série` was already
in this namespace for a diagnostic series, so it arrives with a compatible
sense rather than as a new coinage.

**`_GROUP_WORDS` moved with the catalogue, and that is paper.** Renaming only
the UI would have left the screen showing both words for one thing, because the
label the server composes — `"Groupe 2 · Fractions"` — is rendered in the app
*and* printed on the copy. Sheets already made keep the word they were made
with: `sheet_instance.group_label` stores the label as it stood, so this changes
new proposals only. A pile of old sheets and new ones will use two words; each
sheet is internally consistent, which is the half that matters to a pupil
holding one.

**What is NOT fixed, and should not read as fixed.** The class-code validation
is still `/^\d{1,2}[A-Za-z]{1,2}$/` and still rejects `10-MAT-N2`. Freeing the
word is not the same as being able to represent the thing; that needs the
teaching-group entity, and this pass deliberately stopped short of it.

---

### D92 · One reader at a time, per pile

Found while building F10 on top of D90's append route, and it is a defect that
route introduced. `page_index` and the stored image key (`page-003.png`) both
continue from the rows already written, counted at the start of a run. The
worker runs four jobs at once (`WorkerSettings.max_jobs`), so two runs over one
scan count the same rows, write colliding page numbers, and overwrite each
other's registered images in the bucket.

Not theoretical: pages appear as they are read, so a teacher can be looking at
page 1's registration failure while page 20 is still being processed, and the
retake control was right there under it.

`append_pages` refuses while a `PROCESS_SCAN` job for that scan is queued or
running (`scan_processing`), and the retake control is disabled with a sentence
saying why. Refused rather than queued behind it: "the pile is still being read"
is something a teacher can act on, and the retake is one tap to repeat.

**This is also why F10's batched upload is not built.** The mitigation the audit
asks for — create the scan, then send the photographs in batches so a dropped
connection costs one batch rather than the pile — would issue one append per
batch, which is exactly the concurrency this refuses. Doing it properly needs
the API to accept pages *without* starting a run, or the resumable upload the
audit puts in the API layer. What is built is the half the client owns: the
upload now names the files it is sending, so a teacher can tell a slow upload
from a stalled one and can see that the right photographs were picked.

### D93 · The catalogue answers for every code the API can raise

Phase 4's medium band, and the three entries here are the ones that were
decisions rather than chores.

**Error sentences are generated against, not maintained.** The catalogue covered
thirteen codes; the API can raise thirty-one. Everything else fell through to
`errors.code.fallback`, so a rate limit, a permission refusal, a dead service
and a 500 all told the teacher *"L'envoi a échoué. Réessayez."* Cross-locale
sync could never see it — the thirteen were consistent in all three languages.

So the list is generated from the API itself (`scripts/generate-api-types.py`
scans `_STATUS_CODES` and every `code="..."` under `alppy/`) and
`check-i18n.mjs` asserts a sentence in all three languages for each. A new
`code="..."` now fails the gate rather than silently joining the fallback. The
same generated file carries `SWISS_CANTONS`, for the same reason one layer
down: the settings screen was a free two-character box writing the field a
curriculum mapping keys on, so "XX" was storable, and the picker now cannot
offer what the API would refuse.

`rate_limited` reads `details.retry_after_s`, which the envelope has always
carried and nothing has ever read. "Réessayez plus tard" is not an instruction;
"réessayez dans 42 secondes" is.

**A discard gets an undo by preceding the call, not by reversing it.** The
server's discard is final — "never proposed or printed again" — and there is no
route that restores one, so the toast defers the request rather than undoing it.
Nothing is inconsistent in the window: the export builds from the local plan,
which has already dropped the item, so a teacher who exports inside those eight
seconds gets exactly what they see. What the deferred call decides is only
whether the exercise can be proposed again later. Leaving the screen sends the
pending ones, because a discard nobody undid is a discard they meant.

**One word for the object, and it is `discipline`.** `settings.*` keeps
*branche* — that is the screen where the object is administered, and it is what
a Swiss staffroom says — and everything else that labelled a `Subject` now says
*discipline*, the PER's own term. *Matière* is the France-French word and was
the one that would read as foreign. `École` became `Établissement`: in Suisse
romande the Sek I administrative unit is the *établissement scolaire*, and
*école* reads as *école primaire*.

**The class-code pattern is generated too.** It had drifted once already —
`{1,3}` against the server's `{1,2}`, so `11ABC` passed the form and 422'd at
the API — and was caught by a person reading two files side by side, which is
not a mechanism. `export-layout.py` now emits `CLASS_CODE_PATTERN` from
`alppy/core/uid.py` beside the print geometry it already exports. The pattern
itself is unchanged, and still rejects `10-MAT-N2` (D91).

**What F13 and F18 could not reach.** A *failed* student has no exercise to
regenerate — `AdaptiveRegenerateRequest` takes an `exercise_id` and the whole
point of the failure is that generation produced none — so the per-student
retry the audit asks for needs `POST /adaptive/regenerate` to accept a student
and merge into the stored proposal. The progress half shipped: `useJob` has
always fetched `progress` and the scan screen has always drawn it.

---

### D94 · Projector mode: identity is hidden, data is not

Alppy's screens get projected. The class matrix goes up so the class can see
what the week looked like; the roster is left open while the room fills. Every
one of them put a pupil's name beside a band saying how that child is doing, and
the product had nothing to say about it — it is careful in the other direction,
where no name ever reaches a model provider (`alppy/ai/scrub.py`), and the
audience actually in the room got no consideration at all.

**`discreet` is a display switch**, not a screen option: `data-discreet`,
applied before paint by the same script as the other four, persisted both in
`localStorage` and on the teacher record. It is on the teacher because the
classroom machine and the laptop at home are the same person, and this is the
setting they would least enjoy having to find twice — usually while thirty
pupils watch them find it.

**Names collapse to the UID, and nothing else changes.** Not initials, not a
blur, not a redaction block: the UID is the code already printed on that child's
own paper, so the teacher resolves it from the pile in their hand and the room
cannot. The screen stays exactly as usable as it was, which is what makes the
mode something a teacher will actually leave on.

**Deliberate deviation from the brief.** It also asked for per-pupil bands and
points to sit behind a reveal. They do not. Once the rows are UIDs, a band beside
`7B_04` discloses nothing to the room — a pupil knows their own code and nobody
else's — and hiding the numbers as well would empty the matrix of the reason it
was projected. The disclosure was the *name*, and that is what is gone. Hiding
the data too would have produced a mode nobody switches on.

**Reveal is temporary by construction.** React state in one provider, reset on
every navigation, never written to storage or to the teacher record. A reveal
that persisted would be a projector mode that quietly turns itself off between
lessons, which is worse than not having one. While it is on, the screen keeps
saying so.

**The keyboard reaches it.** Shift+D, from any screen, ignored while the focus
is in a field — a bare letter would fire while a teacher typed a class code. The
realistic trigger for this whole feature is realising you need it when the
projector is already on and the class is already looking, which is the one
moment nobody can go hunting through Réglages.

**F29, the same idea on paper.** A group label is two facts and only one of them
belongs to the pupil holding the page. "Fractions" says what their sheet is
about. "Série 3", against the neighbour's "Série 1", says who is further behind
— and where a large group was split by severity, that is precisely what the
number encodes. `_without_group_number` drops it from the student-facing
feedback page and leaves it everywhere the teacher reads it, including the sheet
header, where it is how one pile of copies is told from another while they are
handed out.

Verified rather than assumed: `e2e/discreet.spec.ts` asserts the name is
**absent from the DOM** — not hidden by CSS, which is a screenshot away from
being readable — on the roster, the matrix, the results screen and a pupil's own
profile, plus the reveal, its reset on navigation, the shortcut, and the
shortcut declining to fire inside a text field.

### D95 · An invalidation that matches nothing looks exactly like one that works

`useUpdateChapter` and `useDeleteChapter` invalidated `['classTree']`. No query
in the app is registered under that key — the real prefix is
`['classes', id, 'tree']` — so the call did nothing at all, and renaming a Theme
left the programme beside it showing the old name until something else happened
to refetch it. TanStack Query does not complain about a key that matches
nothing, because "nothing to invalidate" is an ordinary state; there is no
symptom until a teacher notices the screen disagreeing with itself.

**The fix is a predicate, not a different literal.** A chapter belongs to many
classes and the mutation knows only the chapter, so there is no key that means
"every class's tree" — `everyClassTree` matches on shape instead.
`queryKeys.classTreePrefix` covers the one-class case, so the remaining literal
went too.

**Banning literal arrays would have been the wrong gate.** `['classes']` and
`['sheets']` are deliberate prefix invalidations, and a prefix is by definition
not a key any builder returns. What is checkable is the first segment: if it is
not a namespace `queryKeys` ever produces, the call can never match anything
under any argument. `query-keys.test.ts` asks the builders themselves what those
namespaces are, so it cannot go stale, and it fails on the original bug —
verified by putting the bug back.

**F30 needed nothing.** Both halves had already been resolved by earlier phases:
`errors.notFound.*` is rendered by the `not-found.tsx` that D90 added, and
`school_year_id` is a real generated field on `ClassCreate` rather than a dead
hand-written type — `lib/api/types.ts` no longer mirrors the contract by hand at
all. F32's "stray empty div" was a whitespace-only line, removed with the roster
screen's missing states.

**`docs/plan.md` §5 stays the inventory** and now lists all 24 screens, grouped
by what a teacher is doing rather than by URL. It had drifted by 15 routes
without anyone noticing, which is the argument for gating it — and the argument
against a hand-kept list generally. Kept by decision; the next route added is
the next chance for it to lie.

---

### D96 · Two red gates, and one defect that was never there

Housekeeping that turned out to matter.

**The colour-literal gate was failing on `main`**, and had been: four hits in
TypeScript, so the job that enforces half of DESIGN.md §10.4 was red and
therefore enforcing nothing. A gate nobody can pass is a gate everybody learns
to scroll past.

Three of the four were one file — `mock/fixtures.ts` holds a stand-in for the
API's own print document, a standalone page in an iframe with white paper and
black fiducials and no access to the app's stylesheet. It is paper, and paper is
where the tokens are overwritten rather than read; it gets the same exemption
`print.css` has, named one file at a time rather than by a pattern.

The fourth was real: `shadow-[0_-10px_30px_-12px_rgb(27_23_53_/_18%)]` on the
builder's mobile action bar — `--shadow-ambient` cast upwards, with the rgb
retyped into a component because no token pointed that way. There is one now.

**The visual baselines were stale by two separate things.** The 18 phone
screenshots had been failing before any of this work started (verified in Phase
1 by stashing every change and reproducing them), because the home screen's
discipline chips wrap to a second row now that the fixture school has four
subjects. Then D93's rename made them stale again and more interestingly: the
committed baseline says "BRANCHE Mathématiques" where the app now correctly says
"DISCIPLINE". Regenerated after looking at the rendered output rather than
trusting the ratio — a diff that is purely a vertical offset plus a word we
deliberately changed is a stale baseline, not a regression. The suite is green.

**And a correction.** Two tests in `test_nouns_crud.py` failed in one full run
and passed in the next, and this log would have recorded that as an
order-dependent flake. It is not: `pytest-randomly` is not installed, so the
`-p no:randomly` that "fixed" it changed nothing. The run that failed was at
04:57, which is the minute a second session working in this tree wrote
`open_answer_grading.py` and `scan_processing.py` — the suite was importing
modules as they were being rewritten underneath it. There is no flake to chase.
The lesson is about the tree, not the tests: a shared working directory makes
every red an unreliable narrator.

### D97 · A grade's evidence belongs to the paper it was printed on

Four faults in the path where a child's answers become a child's grade, found by
the phase-3 audit and fixed together because they are one mistake wearing four
faces: **something about the paper was inferred from the present rather than
recorded when it was printed.**

**A decoded UID is read inside one school year (B3).** `_resolve_student`
matched `(school_id, uid)`, but `uq_student_uid` is
`(school_id, school_year_id, uid)` — so the read had no unique index under it
and only ever resolved because every school had exactly one `SchoolYear`. The
second one does not arrive at rollover; it arrives in June, when a school
prepares next year's classes while this year is still marking. From that day the
read raises `MultipleResultsFound` inside a scan job. The year now comes from
the paper — `Sheet → Class → school_year_id` — and `scalar_one_or_none` **stays**:
the loud failure is the good outcome, and `.first()` would turn a visible outage
into one child's answers filed silently under another child's name. With no
sheet there is no year, so no student is resolved and the page waits for manual
assignment, which is the answer `assignable_students` already gave.

**Which page of whose copy stops being a guess (B5).** `page_in_copy` was
`seen[uid] % len(printed_pages)`, and the modulo was the bug: a two-page copy
photographed three times — one page re-shot, the blurred original still in the
pile — wrapped the third photo onto slot 0 and read it against page 1's option
counts. An extra page is now left *unpaired* and flagged rather than placed
somewhere it does not belong. The real fix is a page number printed on the
paper, which is layout v2 (B4) and not this.

**Re-assigning a page is a write (B6).** `assign_page_student` had no
confirmed-pile guard, unlike its three siblings, and is the most destructive of
the four because it re-reads the page — on a confirmed pile it rewrote the very
detections the attempts were graded from. It now refuses. Separately, a teacher's
correction is filed by **exercise**, not by slot: keyed by slot, re-pagination
moves the question and the correction is dropped on the floor. What genuinely
cannot be carried over is deleted *and reported*, by the number printed on the
paper.

**An answer box belongs to one render (B7).** `AnswerBoxPlacement` was deleted
and rewritten wholesale on every render, under a docstring claiming this made it
impossible for a later edit to move the rectangle the scanner crops. It was
exactly how the rectangle moved: print Tuesday, re-render Wednesday for an
absentee, photograph Tuesday's copies on Thursday, and every crop lands at
Wednesday's geometry. `sheet.render_generation` counts renders,
`scan.render_generation` pins the one a pile was printed from — the same job
`layout_version` has always done for the layout — and the slot constraint grows
to include it (0030). Delete-and-rewrite is kept **within** a generation, so the
roster reasoning stays true while earlier generations stay put.

**Warnings are flags, never blocks.** `extra_page`, `short_copy`,
`duplicate_page` and `printed_after_photo` ride on `registration_meta` as codes,
and the client owns the sentence (D86). A teacher with 28 copies must be able to
look and dismiss; being unable to confirm 27 good copies because of one re-shot
photo is the failure `set_page_discarded` was written to end.

**One trap worth naming.** The first version of the warning sweep walked
`scan.pages` and `page.detections`. Both are `delete-orphan` collections and
`_persist_detections` attaches its rows by foreign key, so touching the
relationship materialised it as *empty* and the next flush deleted every
detection on the page as an orphan — a whole pile of readings destroyed by a
function whose only job was to add a warning. The sweep queries rows, and
`_live_pages` says why.

**Still open.** B4 (layout v2: a per-render nonce, a page number and the school
year printed into the grid) is the real fix for B5 and defence in depth for B3,
and is not started — it needs a bit-width design, the cantonal-scope answer, and
dual-decoder support for every already-printed v1 sheet. `printed_after_photo`
is explicitly a stopgap for piles printed *before* 0030, whose placements carry
NULL: if such a sheet is re-rendered, nothing matches and its open items stay
`NOT_GRADEABLE` — no crop, no verdict, counted as skipped, which is the safe
direction. And old generations are never swept, which B14's retention work
should pick up.

---

### D98 · A job that dies says so, a call has a deadline, and a retry does the work once

The reliability layer, which is what turns a transient failure into a stuck
class or an unbounded bill. Nine findings, one shape: **the product assumed
everything it started would finish.**

**A dead job stops holding a pile hostage (B9).** `_run_job` catches every
exception and records `FAILED` itself, so arq's retry never fires — and a job
killed outright (worker evicted, the 600 s ceiling cancelling the task while its
`asyncio.to_thread` thread runs on) left `RUNNING` with nothing to finish it.
`grading_in_progress` reads exactly those rows, so one dead job refused a
confirmation *indefinitely*, with no cancel route: twenty-seven good copies held
by work that ended hours ago. Progress ticks now stamp a heartbeat explicitly —
not relying on `onupdate`, because a tick reporting the same fraction leaves the
row clean and the heartbeat silently stops — and a `RUNNING` job quiet for longer
than `job_stale_after_s` is presumed dead. `python -m alppy.cli reap-jobs` closes
the rows; `is_job_stale` is shared by both so they cannot disagree about who is
alive.

**Retry policy is per kind, and deliberately not uniform.** `RETRYABLE_JOB_KINDS`
holds `PROCESS_SCAN` and `GRADE_OPEN_ANSWERS` — both rewrite what they already
wrote, so a second run costs time. `PROPOSE_ADAPTIVE` and `GENERATE_FEEDBACK` are
the opposite and are why a blanket retry would be a mistake: each writes a second
set of unapproved exercises, or a second note per pupil, and bills the school
again. Nothing consumes the constant yet, on purpose — requeuing is its own
change with its own failure mode, and this is what it has to read.

**Every client has a deadline (B10).** Neither SDK nor boto3 was given one, so
the defaults (600 s, 2 retries) meant a single logical call could hold for half
an hour inside a job whose own ceiling is 600 s — the job was cancelled long
before the HTTP call gave up, which is precisely how a provider blip became a
stuck `RUNNING` row rather than a visible failure. Budgets are settings, and a
batched generation gets its own: a vision call over one crop and a call over
eight plans are not comparable work.

**No transaction spans a provider call (B11).** `regenerate_exercise` discarded
first so `_rejected_statements` would already hold the outgoing item — correct,
and it held a write transaction open across retrieval and a model call. The
discard moves below the generation and what it provided is passed in explicitly:
`seen` is seeded with the outgoing statement. Same guarantee, no lock over the
network. The propose worker commits its retrieval before the generation pass.

**The vision grader is told where instructions come from (B8), and the prompt has
not been switched.** v3 states that everything in the image is the pupil's work
and is data, never instruction, and adds `instruction_like` — routed to
`LOW_CONFIDENCE` whatever confidence the model reports, because a model can be
confident and wrong in exactly the case that matters and `DETECTED` rows are not
what the review screen shows first. A missing field reads as false, so an older
deployment degrades to v2 rather than flagging a whole pile.
`PROMPT_VERSION` **stays v2**: the precondition for moving it is a verdict diff
against real handwriting, and the fixtures for that did not exist — nothing
called `grade_one` at all. `test_open_grading_prompt.py` is that missing net, and
it says in its own docstring what it can and cannot prove.

**An upload is bounded and anonymous (B15).** A phone stamps GPS onto every JPEG,
so a pile photographed in a classroom carried the school's coordinates to object
storage forever, for data the pipeline never reads. And `cv2.imdecode` allocates
the *decoded* raster, so a 40 KB PNG declaring 60000×60000 asks for ~10 GB — the
byte cap cannot see it, because compression is the attack. Metadata is stripped
by **segment surgery, not by re-saving**: a test of this module measured Pillow's
`quality="keep"` moving pixels by ±1, and these are the images a bubble detector
compares against fixed thresholds. Tidiness must not edit evidence.

**A membership can be revoked (B16).** `teacher_school.valid_to` existed since
0027 and `get_membership` checked it from the same day, so a membership was
revocable for two migrations with no route to reach it. Ending, never deleting
(D87). Two refusals: the last member — a staffroom nobody can re-enter, since
membership *is* the permission model (D85) — and a teacher still named as a
class's head, since `Class.head_teacher_id` is NOT NULL.

**A retry does the work once (B17).** The key is **claimed and committed before
the work runs**, which is the whole design: a row written afterwards lets two
simultaneous retries both run and remembers only whichever finished last. A
failed attempt releases its claim, or the first 500 poisons that key forever and
the retry the teacher will certainly make is refused. Per tenant, so one school
cannot probe another's keyspace. `POST /scans/{id}/confirm` is deliberately
untouched: it is already idempotent the better way, by superseding.

**One trap named, because it nearly shipped.** The first version of B5's warning
sweep walked `scan.pages` and `page.detections`. Both are `delete-orphan`
collections and `_persist_detections` attaches rows by foreign key, so touching
the relationship materialised it as *empty* and the next flush deleted every
detection on the page as an orphan — a whole pile of readings destroyed by a
function whose only job was to add a warning. Twenty-five tests caught it. Walk
rows, not relationships, in that module.

**Still open.** The scan-image retention *window* (B14) is a policy decision, not
a technical one: `Storage.delete`, `purge-scan-images` and erasure-deletes-images
have all shipped, and the command **refuses to run** rather than guess a number —
a window a developer invented would destroy the evidence behind a mark the week
before a parent asks about it. Old answer-box generations are swept by nothing
either, and belong in the same pass.

---

### D99 · A number stops moving, a query stops fanning out, and a setting stops hiding

The medium and low findings, cleared in one pass. Individually small; two of them
change what a teacher is shown.

**A returned paper's total stops moving (B18).** `points_earned` was the sum of
`Attempt.score`, frozen at confirmation. `points_possible` was recomputed live on
every read. So the two halves of one fraction came from different moments, and
editing the barème after a pile came back rewrote the denominator of every paper
already handed out — 14/20 became 14/25, silently, on a sheet a parent may have
signed. Frozen onto `SheetInstance`, **per copy rather than per attempt**, and
that departure from the obvious place is the interesting part: an item the grader
could not read produces no `Attempt` at all, so a sum over attempts would leave
those items out of what the paper was worth. NULL until confirmation, so a sheet
still being built keeps tracking the barème.

**A grade names the model that actually answered (B19).** Both providers returned
the *configured* model id. An alias resolves to a dated build that changes
underneath it, so a disputed grade traced back to the configured string named a
model that may never have seen the paper. And the model alone does not identify
the judgement: `Detection.vision_prompt_version` records which prompt produced
the verdict, because the same model under `grade_open_answer.v2` and `.v3` is
told different things about what counts.

**Six tenant filters that were inferences become lines (B20).** `timeline._titles`
selected by primary key alone, reasoning that the ids came from events already
filtered by tenant. True — and true by inference, which stops being true the
moment someone widens the query above. RLS covers these on Postgres; the suite
runs on SQLite, where there is no backstop at all. The comment in `adaptive.py`
claiming to be the only such site is retired rather than corrected: a comment
that counts sites is a comment that goes stale.

**Approval and answer-key edits become legible (B21).** No permission changed —
the flat staffroom stays (D85) — but the two acts that most deserve an author now
have one: approving a generated exercise for print, and editing a sheet after it
has been rendered, which changes what the grader judges against on a paper the
class has already sat.

**The PII gate checks the pattern its own sibling redacts (B22).** `scrub()` had
redacted phone numbers since the beginning; `assert_no_pii` never checked them.
The two halves of one module are meant to know about the same things.

**The home screen stops fanning out (B23).** A band breakdown per class meant a
roster read and a snapshot read per card, on the screen a teacher opens every
morning; `GET /classes` resolved the branch nav per card the same way. Both are
batched, and a test asserts the batched answers equal the per-class ones —
a performance fix that changes an answer is not a performance fix.

**Two domain rules from the brief start existing (B24).** `School.canton` was a
free `String(2)` that accepted "XX", and it is what a curriculum mapping keys on;
it is now validated against **all 26 cantons** — a school in a canton nobody has
piloted should be refused for being wrong, never for being unexpected.
`SheetYear.label` gets a shape constraint, because `current_school_year` looks a
year up BY LABEL: `2026/2027` and `2026/27` would be two years for one school,
two rosters, two sets of UIDs.

**Four settings stop hiding from the config module (B25).** `ALPPY_STORAGE_BACKEND`
was the dangerous one: read straight off `os.environ`, it was invisible to
`_refuse_unsafe_deployment`, so a production deployment that never set it — or
misspelled it — silently wrote scanned answer sheets to a container's temporary
directory. It worked until the container restarted. All four are `Settings`
fields under their existing names, so no deployment changes, and the storage
backend is now one of the things a real deployment is refused for.

**A pile is refused at upload if its sheet is unreachable (B27).** `create_scan`
validated `sheet_id` on tenant alone, and `_owned_scan` then hid the scan the
moment it had a sheet: the upload succeeded, the worker processed it, and the
teacher had no route to the review screen.

**And four small ones (B28–B31).** The session signer names SHA-256 rather than
inheriting itsdangerous' SHA-1 default — not broken, but not a thing to leave
implicit on the line between a cookie and a roster. `/health/live` is a real
liveness probe with no I/O, because the old one opened three connections and a
Redis outage therefore restart-looped every API pod that was still perfectly able
to serve. The engine's pool is sized against `max_jobs` instead of SQLAlchemy's
5 + 10. And the unverified `gpt-*` price rows are named in `UNVERIFIED_PRICES`
and logged when used, rather than only warned about in a docstring — the person
who needs to know is the one reading a cost total, not the one editing the file.

---

### D100 · Layout v2: the paper says which paper it is

B4, the largest and highest-risk item of the three audits, and the only one the
audit told us to schedule deliberately rather than fold into a sprint. **The
design is agreed and the foundation is built; `LAYOUT_VERSION` is still `v1` and
nothing about printing or scanning has changed.**

**Why a bigger grid at all.** v1 encodes only the *pupil*: 8×4 = 32 cells, 24
payload bits (class year, two letters, number) and a CRC-8. Three separate
faults follow from that and all three reached the grading path — a UID resolving
across school years (B3), which page of a copy a photograph shows being inferred
from upload order (B5), and a page from a *different sheet* carrying the same
pupil's UID being read against whatever answer key the pile happened to be
attached to. The paper has to say more than whose it is.

**The bit budget, settled: 12×6 = 72 bits.**

    pupil identity  21   year 4, letters 5+5, number 7 — unchanged from v1
    school year      3   rolling mod 8; defence in depth for B3
    page in copy     4   1..16, stored 0-based; B5's real fix
    canton           5   all 26, per the cantonal-scope decision
    nonce           23   identifies (sheet, render generation)
    CRC-16          16
                  ----
                    72

The nonce is **23 bits, not 24**: the proposal said 57 payload + 16 checksum and
that is 73, one over. Taking it from the nonce costs a 1-in-8.4M false accept
instead of 1-in-16.8M and leaves every other field intact. A test asserts the
sum against the grid rather than trusting this table.

**CRC-16, not CRC-8.** The guarantee the whole scheme rests on is that a misread
grid *fails* rather than resolving to a different real pupil — failing is
recoverable, guessing is not. An 8-bit checksum over 56 payload bits no longer
delivers it. A test walks every single-bit and every two-bit error over the
whole grid and asserts each one is caught.

**The grid moves UP, not down.** Six rows at v1's origin would span y 30..60 and
print over the first exercise, since `ITEMS_TOP_MM` is 48. Pushing the items
region down was the obvious alternative and is the wrong one:
`ANSWER_BOX_MAX_LINES` is calibrated to the millimetre against that region —
"14 lines is 133.3 mm of the 134 mm a page has" — so moving it silently costs a
teacher the tallest answer box they can ask for. At origin y=18 the grid ends at
47, one millimetre clear, and spans x 120..179 with 9 mm to the right fiducial.
It overlaps the fiducial band vertically and that is harmless: the fiducials sit
at x 14..22 and 188..196.

**Versioned geometry is the foundation, and it is what shipped.** The detector
used to read every page against the constants as they exist *today* and refuse
outright on a mismatch — which its own comment called the only honest answer
available, and which meant the first version bump would make every
already-printed sheet unreadable. `layout.UID_GRIDS` now holds a frozen
`UidGrid` per version and `uid_grid(version)` selects one; v1's cells are
byte-for-byte where they were, asserted by a test. Grid order stays column-major
in both versions, because a v2 that reordered cells would let a v1 page decode
to a different real pupil instead of failing.

**The reading half is done and proven on paper.** `scan/detector.py` samples
the grid for the version the page was *printed* with and refuses only a layout
this build has no geometry for — the old "refuse anything but the current
version" was what made a bump unthinkable. `scan/synthetic.py` renders either
layout. `read_uid_grid` returns the decoded `PageCode` alongside the uid, and
`PageResult` carries it.

The degradation suite runs against **both** layouts, which is the condition the
audit set: a v2 page survives `phone_photo` and `copier` with its *whole* page
code intact — not just the pupil, because a scheme that recovers the uid and
garbles the page number would look like it worked — and v1 still survives the
same suite unchanged.

Both cross-version reads are tested and both name nobody: a v1 page sampled as
v2 (the direction that matters once v2 is the default and v1 is what is already
in the drawer), and a v2 page sampled as v1. The CRC is what turns "reads
something plausible out of the wrong part of the paper" into a refusal, and
that is asserted rather than assumed.

**The writing half, and the bump.** `LAYOUT_VERSION` is **v2**. The renderer
lays each sheet out with the geometry *it declares* rather than whatever is
current, prints the page code into the grid, and the pipeline reads
`page_code.page_in_copy` off the paper instead of counting uploads — pages
uploaded backwards now land in their printed order, which is B5's real fix
rather than its mitigation.

**The nonce is derived, not stored.** `sheet_nonce(sheet_id, render_generation)`
is computed by the renderer when it prints and again by the scan pipeline from
the sheet the pile claims to belong to, then compared. No column to migrate, no
row to fall out of step with the paper. A mismatch raises `wrong_sheet` and the
page is left ungraded.

That closes a fault v1 could not even notice: one pupil sits two sheets and
carries the *same UID* on both, so a page of Tuesday's test landing in
Thursday's pile decoded perfectly and was graded against Thursday's answer key —
real marks, real pupil, somebody else's questions. Because the nonce includes
the render generation, it also makes B7's pinning something the **paper**
asserts rather than something inferred at upload.

**One ordering hazard, found by building it.** `_persist_answer_box_placements`
bumped the generation *after* `build_sheet_data` had already run. Under v2 that
would print generation N into the grid and file the rectangles under N+1 — the
exact disagreement B7 exists to end, reintroduced by the fix for B4.
`_open_render_generation` now opens the generation before anything is laid out,
and the placement writer consumes it rather than bumping.

**What the fixture migration exposed.** Bumping the constant turned 57 tests
red, and almost every one was a fixture printing a grid the sheet did not
declare — `render_page` defaulting to "current" rather than following
`sheet.layout_version`. Two of them mattered beyond their own file:
`bits_to_cells`/`cells_to_bits` defaulted to the current version, so pairing
them with `encode_uid` (which is inherently v1) produced 32 bits in and 72 out
the day v2 shipped; they now infer the layout from the run's length, which is
unambiguous because the grids differ in size. And several placement fixtures
wrote a NULL `render_generation`, which since B7 means "printed before
generations existed" and matches no scan — they now write what the render job
would.

**Until then B5's guards stand**, and they are a real mitigation rather than a
placeholder: an extra page is left unpaired and flagged instead of wrapped onto
page 1, and short copies and duplicate slots are flagged for the teacher.

---

**One drift the bump nearly shipped, and the export is what found it.**
`layout.as_dict()` is exported to TypeScript by `scripts/export-layout.py` so
the web print preview and the server cannot disagree about a millimetre, and CI
fails if the generated file goes stale. After the bump it reported
`layoutVersion: "v2"` beside **v1's grid** — 8x4 at y=30 — because the bare
`UID_GRID_*` constants had been left behind as aliases whose comment claimed
they tracked the current layout and whose values did not. The preview would have
drawn the old grid in the old place while the server printed the new one, and
both sides would have agreed on the stale number, so the very check built to
catch this would have walked past it.

Those constants are **gone**, not corrected: a name that reads as "the current
grid" is a trap once two layouts are live. Callers ask `uid_grid(version)` and
say which version they mean. `uid_code`'s v1 sizes now come from
`uid_grid("v1")` explicitly — they had been derived from those aliases and were
right only by accident, an accident that would have ended the moment anyone made
the aliases honest. The export carries `uidGrids` for **every** readable layout
alongside `uidGrid` for the current one, because a preview of an
already-printed v1 sheet has to be drawn as v1.

**And the prompt moved.** `PROMPT_VERSION` is **v3** (B8). The precondition was a
verdict diff between the versions, and there were no fixtures to produce one —
nothing called `grade_one` at all. `test_open_grading_prompt.py` is that missing
net: identical model output through both versions produces an identical
`Detection` for every answer shape the grader already handled, so the change is
additive. The one deliberate difference is `instruction_like` routing to
LOW_CONFIDENCE whatever confidence the model reports. What this does **not**
rest on is how a real model reads the reworded prompt; that needs an evaluation
against real handwriting, and reverting is one constant.

---

### D101 · `fr-CH` never meant what three files said it meant

Audit 05 §10.1 dismissed the brief's §54 — which asked for Swiss decimal handling
— on the grounds that the repo had already settled it correctly: *"ICU agrees —
`fr-CH` is `.` for decimals and `’` for groups. So `fmt.number(4.5)` renders
`4.5` and that is correct for the locale."* `lib/format.ts` said the same thing in
its own header: *"`fr` alone would print `1 234,5`; Suisse romande writes
`1'234.5` … hence `fr-CH`"*.

Both are false, and they were checked rather than reasoned about only when a test
asserted the output. CLDR's `fr-CH` is byte-identical to plain `fr`:

| tag | 1234.5 | 0.25 |
|---|---|---|
| `fr` | `1 234,5` | `0,25` |
| `fr-CH` | `1 234,5` | `0,25` |
| `de-CH` | `1’234.5` | `0.25` |
| `en-CH` | `1’234.5` | `0.25` |

Only the Germanic tags carry the apostrophe group and the period decimal. The
`fr-CH` mapping bought French **nothing**, and had bought nothing since it was
written. Verified identically under Node's ICU 76.1 and the Chromium the e2e suite
ships against, so this is not a build-environment artefact.

**Two consequences, one of them a real defect.** French was never inconsistent —
both halves wrote a comma. **German was**, and nobody had looked: a catalogue's
own `{points, number}` is formatted by next-intl with the app locale (`de` → a
comma) while `lib/format.ts` formats with `de-CH` (a period). A German teacher
read `Total: 2.5 Punkte` above `0,5 Pkt.` in one panel, and on a returned paper
`3.25 / 4,5 Pkt.` on one line.

**The fix is two-layered, and the layers answer different questions.** The nine
catalogue messages that formatted a number no longer do: they take a plain
`{points}` and the caller passes `fmt.number(v, 2)`, so every number in the
product comes from the one authority `format.ts`'s header always claimed it did.
Two fraction digits, not the default one — a quarter-point penalty is a real
barème and `0.3` is not it. Then `format.ts` substitutes the group and decimal
marks itself, through `formatToParts`, in every locale.

That substitution is a **deliberate departure from CLDR for `fr`**, and it is the
part worth disagreeing with. Suisse romande prose does write a comma; the brief
was right about that and §10.1 was wrong to wave it away. The argument for
overriding it anyway is that a barème, a points total and a class average are
figures on a school document rather than prose, `1’234.5` is the convention a
Swiss teacher reads there, and one product should not punctuate the same barème
two ways depending on which of three UI languages is selected. U+2019 is pinned
rather than read off `de-CH`, so an ICU upgrade cannot move the French UI on its
own.

`lib/format.ts` had no test at all (G32) — the single highest-leverage untested
file in the repo, and the reason a false claim about ICU survived in a comment
long enough to be repeated in an audit and then acted on. `format.test.ts` pins
all three locales, asserts they agree, and asserts no decimal comma is ever
emitted. It is also why G2's comma-INPUT support is not a nicety: a field may
display `0.25` now, but a Romand keyboard still produces `0,5`, and a teacher's
own separator has to be readable whatever the display convention is.

---

### D102 · Capability that reached the types and stopped there

Audit 05 names a pattern rather than a bug: the backend added a school-year
dimension, an `as_of` parameter and an idempotency-key mechanism; the generated
types and the endpoint wrappers knew about all three; nothing above that layer
touched any of them. This is worse than an honest absence, because a reader who
finds `asOf` typed in `endpoints.ts` reasonably concludes it is wired up. Four
instances were found, three of them named in the audit and one not.

**The school year (G3).** `GET /school-years` was served, `school_year_id` typed
on four routes and `as_of` on five, and `grep -n "schoolYear\|asOf" queries.ts
scope.tsx ScopeSwitcher.tsx` returned nothing. Now wired, and two decisions inside
it are the interesting part.

*`as_of` is not `school_year_id`.* The id says which year's objects to list; `as_of`
rewinds the mastery model — attempts after it are dropped, the decay is measured to
it, and the roster moves with it. Selecting a past year and leaving `as_of` at "now"
would decay that year's attempts by however long ago it ended and show a class that
had learnt nothing. So the year derives both: the id for `/home`, `/classes`,
`/sheets` and `/scans`; `ends_on` at **end of day** for the mastery reads, because
the date alone parses to midnight and would drop the final day. The current year
sends no `as_of` at all, since "now" is what every read meant before this existed.

*The year is in the KEY, not just the request.* Without that, switching year serves
the year you left out of cache and a teacher reads last year's figures under this
year's heading — the failure mode that makes this worse than no feature. `home` and
`classes` grew a segment, so the bare arrays became `homePrefix`/`classesPrefix` for
invalidation; TypeScript found all fourteen sites. The class list key is
`['classes', 'list', year]` and not `['classes', year]` on purpose: `klass(id)` is
`['classes', id]`, and a year id in the same slot as a class id is a collision
waiting for the first invalidation that guesses wrong.

*It is its own module, and its own provider.* `lib/scope.tsx` imports from
`lib/api/queries`, so `queries` cannot import `scope` — and the year has to reach
the hooks. Threading it through eighteen call sites is eighteen chances to forget
one. So `lib/school-year-context.ts` holds the context and imports nothing but
React and the API types; `lib/school-year.tsx` holds the provider, which needs the
router for `?year=`. That split is not tidiness: with them together, `queries.ts`
— and so every consumer of `queryKeys`, including its unit test — transitively
required a Next router, and `query-keys.test.ts` went red.

The year is also not a filter. Class, subject, Competence and Theme narrow what you
see within one context; the year replaces the context. Keeping it in `ScopeValue`
would have invited the same "just another chip" treatment, and this is the one
selection that must never be quiet — hence a full-width bar on every screen, naming
the year in words with the way back beside it, not a chip.

**The idempotency key (G4).** `RequestOptions` had no `headers` field at all, so the
key could not be sent from anywhere, while the API had claimed one on four routes
and two translated refusal sentences sat in the catalogue waiting for a request
that never arrived. The part worth getting right is that the key belongs to the
teacher's **intent**, not to the request: minted per request it is a new key on the
retry, which is the case the mechanism exists to collapse. `useIdempotencyKey`
holds it in a ref, `clear()` runs on success only, and `restart()` exists for the
one case a retry must not cover — a different file selection, where reusing the key
would have the server answer with the pile built from the previous one. Passing
`api.renderSheet` bare became a type error in the process, which is luck worth
noting: react-query calls `mutationFn` with its own context object, and it would
have gone out as `Idempotency-Key: [object Object]`.

**`pupilLabel` (not in the audit).** The audit describes it as "already
unit-tested", which is true, and implies it is in use, which it was not: it had no
production caller anywhere. Its `Pupil` type also required non-null names, so it
could not accept a real `StudentOut` — which is part of why nobody had called it,
and why `CellDrillDown` formatted a name by hand and would have rendered a literal
`"null null"` for a pupil anonymised by an erasure request. Widened to the real
shape, and the visible case now delegates to `studentName` so the two answers to
"what goes where a pupil's name goes" cannot drift.

**What stays unwired, deliberately.** `updateSheet` has no caller and gets none:
the absence of a client edit path is what closes the re-render-after-print risk.
`SourceOut.error` and `.notice` are teacher-facing prose but English-only and
hard-coded server-side (two error values, two notices); rendering them off a code
needs `error_code`/`notice_code` on the schema, and building the client half first
would be one more instance of the very pattern this entry is about.
`ScanPage.registration_error` stopped being rendered outright — see D103.

---

### D103 · The detector's English stops reaching the wall

`ScanPage.registration_error` was rendered straight onto the scan review screen.
Its three possible values, from `scan/detector.py`:

- `"sheet was printed with layout v1, which this detector has no geometry for"`
- `"registration quality 0.42 is below 0.55: the four marks found do not form a page"`
- `str(exc)`, from a `RegistrationError`

The third is the case D86 exists to forbid — *an exception's own text is never
assigned to a field a browser reads* — and this is the screen a teacher projects
onto a classroom wall while correcting a pile. The second is a threshold nobody
outside this repository can act on. All three are English in a French product.

It is no longer rendered. The two sentences already above it (`registrationWhy`,
`registrationHelp`) say everything actionable, in the teacher's language, and the
retake control beside them is the action. Putting the reason back means
`registration_error_code` on `ScanPageOut` plus a catalogue entry per value, the
way `Job.error` already works through `FAILURE_CODES` — the field keeps its place
in the API's own logs meanwhile.

Worth naming: `Source.error` is **not** the same case and was left alone.
`ingest/pipeline.py:_teacher_facing_error` is a deliberate two-value map with a
docstring saying passing an exception's text through it is not allowed, so that
field is prose written for a teacher. Its remaining fault is that the prose is
English, which is a schema change and not a rendering one.

---

### D104 · Three findings answered by disagreeing with them

Most of audit 05's low-severity list was straightforward. Three were not, and the
reasoning matters more than the diffs.

**The review screen names the pupil (G24).** A dignity call, and it went the way
the audit leaned. This is the screen where a paper is attributed to a child, and
the UID is the MACHINE's channel: a teacher holding the copy cannot check `7B_04`
against anything, but they can check "Liam Dubois". It is the one misattribution
check a machine cannot make, and a misread UID putting one child's marks on
another's record is the worst thing this screen can do. The code still leads,
because the code is what is printed on the paper; the name follows. Projector mode
takes the name away and leaves the code, unchanged.

Adding it exposed that `GET /scans/{id}/students` had no fixture handler at all, so
the list came back empty — which also meant the page-assignment picker had never
had any options in fixture mode, and no test had noticed.

**The roster keeps its em dash (G30).** The audit asked for the UID here, for
consistency with every other screen. Declined: every other screen has nowhere else
to put the UID, and this row already shows it in the column immediately to the
left. Printing it twice is noise on the one screen a teacher scans down looking for
a particular pupil, and the existing comment had already made that argument.

What the dash *did* get wrong is what it says to a screen reader — "7B_04, em dash"
reads as a missing value rather than a withheld one. The dash is decoration now and
a visually-hidden "Nom masqué" carries the meaning. The finding pointed at a real
defect; its proposed remedy was the wrong one.

**The `n` shortcut keeps its binding (G25).** `n` and `Shift+D` are browse-mode
quick-nav keys in NVDA and JAWS, so a screen-reader user in browse mode never
reaches the handler — the reader consumes the keystroke and nothing in JavaScript
can tell that it did. A different letter only moves the collision. What makes the
function equitable is a real control in the tab order, and there is one: the
"Élément suivant" button calls the same `goToNext`, with the `KeyboardHint` beside
it as a hint rather than the only route. Changing the binding would cost sighted
keyboard users a good shortcut and buy screen-reader users nothing. Documented at
the handler instead.

**And one answered by reading it.** Open question 7 asked, for the second audit
running, whether `docs/plan.md` §5 is the screen inventory of record. It is, and it
is accurate — someone had already brought it from eleven screens to twenty-four.
What it lacked was anything stopping it going stale again, which is why the question
kept coming back. `pnpm screens:check` compares §5's paths against the route tree in
both directions. Not generated, unlike §4's route list: each line of §5 says what a
screen is *for*, which is the only reason to read it and which no generator can
produce. The prose stays written; the check guards the set of paths, which is the
half that drifts silently.

---

### D88 · The audit's remaining findings, and the two it was wrong about

Phase 1 (D87) fixed the two Critical findings. This is everything else in
`docs/audits/01-database-audit.md` that was worth doing, plus two places where
checking the source changed the answer.

**The drift gate was blind to the thing it had already missed.** Alembic does
not compare `server_default` unless asked, and `check-schema-drift.py` never
asked — so the gate that exists to prove "the migrations reproduce the models"
could not see the class of drift that produced 0025. Turning `compare_server_default`
on surfaced exactly the seven the audit predicted, all the same shape: a DEFAULT
in the database that no model declared. All seven are now declared on the
models rather than dropped from the database, because the database's default is
the one that covers a write the ORM did not build — a backfill, a seed, a psql
console. One of them is written `'[]'` and not `'[]'::jsonb`: Postgres coerces
an untyped literal to the column's type, and SQLite — where `create_all` builds
the suite's schema — renders the cast verbatim into a CREATE TABLE and rejects
it.

**Eighteen redundant indexes, not the audit's seventeen, and the list is
derived rather than copied.** The schema had moved eleven migrations since the
audit ran. The rule — non-unique, non-partial, btree, single column, and some
other index on the table starts with that column — is mechanical, so it is run
against the live catalogue instead of trusted. Seven of the eighteen are
`school_id`, which is worth saying out loud because 0024's RLS policy compares
that column on *every statement*: they are dropped only where a composite on
the same table already *starts* with `school_id`, so the prefix scan is the
same scan. `attempt`, where nothing leads with it, keeps its index. The models
carry the claim (`__school_id_index__`, `_fk(index=False)`) so the gate can
check it, and every site names the index that covers it.

**A latent bug found while adding a constraint, not while looking for it.**
`postgresql_where` is dropped on other dialects, so on SQLite — where the suite
actually builds its schema — every PARTIAL unique index had been an ABSOLUTE
one. `uq_class_student_open` was quietly forbidding a pupil from ever rejoining
a class they had left, which is precisely the case D87 widened the key to
allow, and no test had asked. All of them now carry `sqlite_where` too.

**The read audit trail goes where the subject is known, not where the plan said.**
`access_log` answers "who looked at my child's file", which `event` — a write
log of eleven product verbs — cannot. The plan put the write in
`deps.get_membership`, which resolves actor and tenant on every request but not
*which pupil*; a log without subjects answers nothing, and the table's own
`subject_type`/`subject_id` columns say so. So it writes from the two gates that
already decide whether this teacher may see this child. `subject_id` is
deliberately not a foreign key: the question is most worth asking about a pupil
who has since been deleted. The write is best-effort and never fails the read —
a lost row is a gap in a trail, a raised exception is a class nobody can open
on a Monday morning — and that trade is the reason the retention sweep is the
only other writer.

**Where the audit was wrong, checked against the source.**

*Pythagoras is composante 8, not 5.* The audit said to move the theorem from
`MSN 31` to `MSN 34` composante 5. CIIP's own API puts it under `MSN 34`
composante **8** — "…en utilisant des procédures de calcul de longueur
(théorèmes de Thalès, de Pythagore…)" — in the section "Calcul de grandeurs",
Niv 1 in 11H and Niv 2-3 from 10H. The move happened; the number did not come
from the audit.

*The PER is fetchable as data, not only as PDFs.* The audit proposed parsing
`PER_print_MSN_*.pdf` with `pdftotext -layout`. `per.ciip.ch/api` is CIIP's own
service behind the public viewer and returns the whole structure as JSON —
levels as fields rather than indentation. `scripts/fetch-per-curriculum.py`
uses it, which makes the seed reproducible instead of the output of a parse
nobody will re-run.

**The real curriculum lands BESIDE the invented one, not on top of it.** 373
official rows in a `2023` edition — 1 domaine, 5 objectifs, 41 composantes, 270
progressions carrying their year, 56 attentes fondamentales — every one citing
the endpoint it came from. The sixteen hand-authored rows stay, in a `2010`
edition, marked `is_official = false`. Overwriting them would have rewritten the
rows every existing band was computed from and broken every chapter and test
still pointing at them, for no gain a second edition does not give. That is what
`edition_id` is for, and widening `uq_competency_code` to carry it is what makes
it possible. `edition_id` is NOT NULL for a reason that is easy to miss: two
NULLs are distinct inside a unique index, so a nullable version would have put
the same hole in the new key that M4 had to close on `attempt`.

**M5 is deliberately not done, and this is the argument.** The audit proposed
converting `MasteryBand`, `CurriculumKind` and `Locale` from Postgres enums to
lookup tables, so a change needs a row rather than an `ALTER TYPE`. Rejected,
because for these three the row is never the whole change:

- a sixth `MasteryBand` needs a colour token calibrated to 0.46 luminance, a
  band glyph, a print underline style and a rule in `mastery/model.py` — a
  lookup table would let somebody insert a band that nothing can render and
  nothing can compute;
- a third `CurriculumKind` needs a seeded curriculum, which is `competency`
  and `curriculum_edition`, not an enum member;
- a fourth `Locale` needs a message catalogue, which CI already enforces exists
  in three.

The test the audit applies to `stream` — "can a canton be added without a
migration" — is the right test, and `stream` is a lookup table because it
passes it. These three fail it. A lookup table here would move the constraint
somewhere it cannot be checked, which is the opposite of the flexibility it
looks like.

**Revisit if** a school needs to mark against two editions at once (today
`School.default_curriculum` picks a curriculum, not an edition, so the newest
edition wins by being the one chapters point at); or if `access_log` grows
enough that the retention default of a year is the wrong shape and it wants
partitioning rather than a sweep; or if a `MasteryBand` ever genuinely has to
be school-configurable, at which point M5's argument is worth re-reading rather
than re-deriving.

---

## Audit 06 — the test estate

**The live loop runs nightly, not on every PR, and the reason is that it found
something (T2).** `live-loop.spec.ts` has existed all along and was skipped in
every run, because nothing ever set `ALPPY_LIVE_API`. So 197 of 217 behavioural
E2E tests replaced `apiRequest` before `fetch`, and CI had never once exercised
HTTP, JSON serialisation, status handling or error mapping. The first time the
spec was actually run it failed — and the failure was the same shape as the two
incidents that motivated writing it: **the sheet builder posts
`subject_id: ''`** when no subject is in scope, and `POST /sheets/propose`
answers 422 `uuid_parsing`. The mocked suite cannot see it; the fixture layer
accepts an empty string where the API requires a UUID.

Two consequences, recorded rather than left implicit:

* The spec now names its class and subject in the URL (`?class=&subject=`),
  which `scope.tsx` resolves before falling back to stored state. That is what a
  teacher's own navigation does, and it is not a workaround — arriving at the
  builder with nothing in scope is a real state, and the *product* answer to it
  is still open: the propose button is enabled while the request it would send
  cannot succeed, and a teacher who presses it gets a raw `uuid_parsing` message
  rather than a sentence. Left to the frontend workstream, whose file this is.
* The job is `schedule` + `workflow_dispatch` in its own workflow, not a job in
  `ci.yml` on `pull_request`. Two of the seven live tests still fail on the F1
  and F2 builder loops, and a merge gate that is red on arrival is a merge gate
  somebody deletes within a week. It runs, it reports, the failures get fixed —
  then it moves to `pull_request` and becomes a gate.

**A reading the machine was unsure of is not a grade until a person looks
(T24).** `LOW_CONFIDENCE` was counted for a report and gated nothing, so a
teacher who confirmed a pile without opening it turned every unsure reading into
a mark. It now blocks confirmation, and the refusal names `detection_ids` rather
than a count because the teacher has to go and open rows. What makes that
affordable rather than a wall in front of a thirty-copy pile is that reviewing
is not disagreeing: `correct_detection` stamps `CORRECTED` whatever value it is
sent, so a teacher who looks and agrees affirms by re-sending the same reading.
`MULTIPLE`, `NOT_GRADEABLE` and `BLANK` still confirm — they score nothing and
are counted as skipped, and stopping a pile because a child left an item empty
would be a different product.

**The school year turns over in Swiss time; a membership change does not (T5).**
`current_school_year` defaulted to `datetime.now(UTC).date()`, and at 00:30 on
1 August in Sion it is still 31 July in UTC — so a school set up that evening was
given the year that ended the day before, durably, because
`current_school_year` resolves a year BY LABEL when one already exists.
`school_today()` is Europe/Zurich. `validity.today()` stays UTC: it stamps a
membership change, where being a couple of hours early costs nothing because no
read path compares it to a wall clock finer than a day, and making it injectable
would touch twenty call sites to fix a problem that is not one.

---

## Phase 7 — deployment preparation, phase 0

Everything below is code or configuration with no external dependency: no host,
no vendor account, no paperwork. They were taken together because each one is
small and the *combination* is what moves the security posture — and because the
phases that follow are all blocked on decisions this repository cannot make.

**The container images have one dependency list each, and it is the manifest
(D16, D17).** Both images carried a fallback — `pip install -e . 2>/dev/null ||
pip install <inline list>` and `pnpm install --frozen-lockfile || pnpm install` —
and the Python one had already drifted: no `openai`, which is the default chat
provider, and no `pillow-heif`, which is how an iPhone photograph of a pile of
copies is decoded at all. `2>/dev/null` meant nothing said which branch ran. Both
fallbacks are gone; the editable install now works because `alppy/__init__.py` is
copied in beside `pyproject.toml`, which is what setuptools needs to resolve
`packages.find`, and which changes about once a year so the dependency layer
still survives a source-only rebuild.

**HSTS is emitted by the middleware, not by `next.config.ts` (D23).** Next
evaluates `headers()` during `next build` and freezes the result into
`routes-manifest.json`, so a header gated on the *runtime* `ALPPY_ENV` — which
this one has to be, or `docker compose up` pins `localhost` to HTTPS in the
developer's browser for a year — would be decided by whatever the build machine
had set. A browser applies HSTS to the whole host from any one response, so the
document responses the middleware handles are enough. No `preload`: that is a
submission to a browser-vendor list that is slow to leave, and the production
domain is not settled.

**The session key is a ring, and `itsdangerous` takes it as a list (D24).** The
audit suggested `fallback_signers`; that argument rotates the *algorithm*, and we
name the digest explicitly and have never changed it. The key ring is the
list-valued `secret_key`, where the last entry signs and every entry verifies —
so `_serializer` builds `[*fallbacks, primary]` and the order is the contract.
What this buys is that rotating a key is a procedure (add, deploy, wait out the
12-hour session lifetime, drop) rather than logging every teacher in every school
out mid-lesson. A key that can only be rotated by causing an outage is a key that
never gets rotated, which is not the state a leaked one should find us in.

**`/health` answers a verdict; the breakdown moved behind a token (D35).**
Which of Postgres, Redis and the object store is down is a map of the deployment's
internals, and it was offered to anyone, unauthenticated, on the one route whose
job is to answer when everything else cannot. `/health` keeps `ok`/`degraded` —
that is the whole of what an orchestrator does with it, and a readiness probe
that needs a cookie is a readiness probe that fails. `/health/detail` carries the
components, is open in `local`/`ci`, and everywhere else needs
`ALPPY_HEALTH_DETAIL_TOKEN` and answers **404** rather than 401, because a 401
confirms the route is there. A token rather than a network check because behind a
reverse proxy every request arrives from the proxy, so "the peer is private" is
true of the whole internet; a genuinely internal listener is an infrastructure
decision that has not been made.

**The web app has a configuration module, and it refuses (D27).** `lib/config.ts`
is the web half of `core/config.py`: every `process.env` read in one place,
validated once, throwing at import. The check that earns it is
`ALPPY_MEDIA_ORIGINS` against `ALPPY_S3_PUBLIC_ENDPOINT_URL` — out of step, the
scan review screen renders its rows, its verdict buttons, and empty frames where
the crops should be, with the only explanation in the browser console. The
compose file now passes the endpoint to the web container so the two can be
compared at all. Two shapes on purpose: `readWebConfig()` re-reads the
environment on every call, because the middleware runs per request and the
compose stack sets these at runtime, and `assertWebConfig()` runs once at import.

**`make down` keeps the data; `make nuke` asks (D34).** `down -v` drops the
Postgres volume — a term of graded work, and there are no backups to restore it
from — and `make down` is one keystroke from `make up`.

**Migrations take an advisory lock (D13, half).** Two API containers starting
together both ran `alembic upgrade head` against the same database, and alembic's
per-migration transaction stops a half-applied revision, not two processes
applying the same one. `pg_advisory_lock`, session-scoped and released in
`finally` — not the transaction-scoped variant, because a migration is free to
commit and would drop it mid-run. Moving the migration out of the serving
container's start altogether is the other half, and it belongs with a deploy
pipeline that does not exist yet.

**The development compose file says what it is, and publishes to loopback
(D5).** Every credential in it has a working default, which is the point on a
laptop and a breach on a server. Docker publishes to `0.0.0.0` by default and on
Linux opens the firewall to do it, so `docker compose up` on a VPS put Postgres,
Redis and the MinIO console on the public internet with password `alppy`.
`127.0.0.1:` on every data service costs local development nothing.

**`store=False` on the OpenAI grading call (D6, one lever).** The Responses API
keeps the request and response for 30 days by default, and this is the call
carrying a photograph of a named child's handwriting — the crop goes out because
the PII gate reads text and geometry is what keeps the name off the image. That
would be a copy in a third country under a retention window we neither set nor
sweep. It is one lever and not the whole finding: the transfer still happens, and
still needs a DPA and a provider decision.

**`WorkerSettings` reads its own settings (D22).** `job_timeout` and `max_jobs`
were literals while `job_timeout_s`'s docstring said otherwise, and
`job_stale_after_s` — what the reaper uses to decide a `RUNNING` row has nobody
behind it — is derived from the setting. So raising it moved the reaper's
threshold and not arq's ceiling, and the two stopped describing the same job.
`worker_max_jobs` is now a setting rather than a literal because worker sizing is
a deliberate choice: `db_pool_size` is sized against it, and a scan pipeline pins
a core.

---

## Phase 7 — deployment preparation, phases 1 to 6

Several of these were blocked on decisions the repository cannot make. Rather
than stall, each was taken as an explicitly-stated MVP default, chosen to be
cheap to change and recorded here so that changing it is a decision rather than
a discovery.

**The scheduler lives in the worker, not in a provider's console (D2).** arq
supports `cron_jobs` natively and the worker is already a persistent process
holding the right credentials, so there is nothing to provision; it is reviewed
and tested beside the tasks it schedules; and it survives a host migration
without anybody remembering to recreate it. A scheduler configured in a console
exists on exactly one provider, and the host is not decided. The reaper runs
every five minutes and at startup — a worker coming back from a crash is
precisely when there are stale `RUNNING` rows blocking a teacher's confirmation
— and the purges run nightly and staggered, and NOT at startup, because a worker
restarting six times during a deploy must not purge six times. Every job body
runs in a thread and swallows its failure after logging: all four are
idempotent, so the next run does the work the failed one did not, and a purge
that cannot reach object storage must not take the reaper down with it.

**Scan-image retention defaults to 400 days (D3).** The old default of 0 —
keep forever — was right for exactly as long as nothing enforced any number: a
window a developer invented would have destroyed the evidence behind a mark the
week before a parent contested it. It stopped being right the moment the real
alternative became an unbounded, permanently growing store of photographs of
named children's handwriting. 400 days is a school year plus one term, so a mark
given in June is still appealable against the page the following spring. It is a
starting position, not a school's policy. Per-school and per-canton windows are
flagged and not built: that is a column on `School` read per pile by the purge,
and it belongs with the data model.

**Fly.io in `zrh`, as a starting position (D4).** It runs a persistent process,
which the worker needs and Cloudflare's free tier cannot give; it is what
`deploy-cloudflare.md` already assumed; and Zurich means the machines and volumes
are in Switzerland. The honest limit is stated in the file rather than buried:
Fly is a US company, so a cantonal IT department asking about the CLOUD Act gets
a better answer from Exoscale or Infomaniak. What makes it cheap to reverse is
that everything Fly-specific is in two files. **Nothing is provisioned and
nothing has been deployed from them.**

**Migrations move to a release step (D13, the larger half).** `release_command`
runs `alembic upgrade head` on one machine and the release does not proceed if it
fails — so a failed migration is a failed deploy rather than a crash loop. The
compose entrypoint keeps migrating on start, because that is what makes
`docker compose up` one command, and now says in the file that this is a compose
convenience. The advisory lock is what makes having both safe.

**One lockfile is the resolution and one is what pip installs (D18).**
`uv.lock` is universal and regenerable; `requirements.lock` is the hashed,
pip-consumable export the image installs with `--require-hashes`. Adding uv to
the runtime image would be a second thing to keep current for no gain. This
matters more here than it usually would: the scan detector is numerical code and
its degradation suite is calibrated against a specific OpenCV/NumPy pair.

**`--workers` and the Redis rate-limit buckets are one change (D19, D30).**
Each uvicorn worker held its own bucket dict, so N workers silently multiplied
every ceiling — including the one in front of sign-in — by N. A limit that is
still configured, still enforced, and worth four times what it says is the worst
of the three possible states, so `_refuse_unsafe_deployment` refuses the
combination outright. The shared bucket is a Lua script, because
read-modify-write from Python is three round trips with other workers racing
between them; it reads Redis's own `TIME`, because two processes with drifting
monotonic clocks would refill one bucket twice. A Redis outage degrades to this
process's own bucket: a weaker limit, never no limit and never a refusal —
raising would lock a school out of its own product, and returning "no wait" would
remove the brake in front of Argon2id exactly when the system is already
unhealthy.

**The override rate is a column comparison, not an outcome count (D8).**
`correct_detection` stamps `CORRECTED` whether the teacher agreed or disagreed
(T24), so counting outcomes measures *attention* and reports it as error. What
`health_signals` measures is the stored value differing from the write-once
`machine_*` columns, and it reports the review count beside it, because an
override rate over a pile nobody opened says nothing about the scanner.
Registration failure rate is the third signal and the most diagnostic: a page
whose fiducials cannot be located produces no readings at all, so a school whose
photocopier has drifted *disappears* from the override rate rather than showing
up in it. Logged rather than written to a summary table — a trend needs history
and a table is the better answer, but the thing missing today is the number, not
its archive.

**The spend cap bounds what can be STARTED, not what finishes (D21).** It sits
beside the rate limiter at the API boundary rather than inside
`AiClient.complete`, for two reasons: `AiClient` is deliberately usable with no
database at all, and a check at the point of the call abandons a class set
half-graded — which is a worse thing to hand a teacher than a ceiling overshot by
one job. 402 rather than 429, because this is not "slow down" and a client
retrying on 429 would hammer a door that is not going to open. The defaults
(20 CHF a day, 200 a month, per school, on rolling windows) leave room for one
textbook ingest: a cap nobody can run the product under gets raised to infinity
on the first bad afternoon.

**The error tracker's `before_send` is the load-bearing part, not the
boilerplate (D8).** A default-configured tracker sends the request body, and on
this API that body is transcriptions of what a named child wrote, presigned links
to photographs of their handwriting, roster names, or a password. Body, cookies
and credential headers are dropped, the query string is redacted, and context is
scrubbed by key to a bounded depth — error reporting must never become the
outage. Session replay is *absent* rather than sampled at zero: a default that
can be raised by editing one number is a different thing from an integration that
never had it. The SDK is an optional extra, so the default image carries no
tracker and the absence is reported once at startup.

**Paperwork: three documents drafted, three deliberately not.** The subprocessor
table, a DPIA outline with the factual sections filled in from the code, and a
breach procedure whose order of operations is stated and whose names and
timelines are blanks. The DPA, the processing register and the parental privacy
notice are not drafted in substance — they carry legal weight, and a
plausible-looking draft is worse than an empty section because it gets signed.
The premise that changed for all of them: the shipped default AI provider is
offline, so no personal data currently leaves the deployment, which makes "no
transfer until there is a DPA" a position that can be held rather than a reason
to wait.

**Rollback policy, decided: the application rolls back, the database rolls
forward.** `alembic downgrade` is never run on a production database — several
migrations are irreversible in substance, and a `downgrade()` that restores a
*column* does not restore what was in it. The consequence is a rule rather than a
preference: a release containing a destructive migration must say so in its own
commit message and cannot be rolled back, which means it is deployed on its own
and never bundled with a feature. A rename that has to happen is two releases,
each individually rollback-able.

**The restore procedure is written and has never been run, and says so.** An
untested backup is a belief, and the moment it is needed is the worst moment to
find out it was wrong. It also records the consequence that is easy to miss: a
backup window is the window in which an erasure is not really complete, so a
restore has to re-apply every erasure since the restore point — from a log kept
outside the database being restored, which does not exist yet.
