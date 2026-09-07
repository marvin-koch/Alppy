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
