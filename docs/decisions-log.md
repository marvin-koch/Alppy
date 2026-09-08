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
  of 8 mm, filled with lines, the 5 mm notebook grid, or nothing. Presets
  rather than a free height because pagination reserves room for exactly
  these; a fill choice because a drawing wants a grid and a sentence wants
  lines. Chosen by the user; the fill was added at their request.
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

