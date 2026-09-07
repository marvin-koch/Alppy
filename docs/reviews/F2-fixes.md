# F2 — what was fixed, and how it was verified

Companion to [`F2-review.md`](F2-review.md), which recorded the findings. This
records what changed and what was actually run to confirm it. Everything below
was verified by executing it against the running stack, not by reading the diff.

The detector was not the problem and is almost untouched: it read 8 640/8 640
items and 0 wrong UIDs under degradation before any of this. What was broken was
the layer between it and a graded attempt, and `scan_processing.py` — where four
of the five worst defects lived — had **no tests at all**. It now has eighteen.

---

## The four blockers

**The UI could not upload (P0-1).** `endpoints.ts` posted the file part as
`files`; `api/v1/scans.py` declared `file`. Every browser upload was a 422 before
it reached the worker. The API now takes `files` as a **list**, because
photographing a class set gives one file per copy and 28 photos are one pile to
review, not 28 scans — `Scan.storage_keys` holds them in the order they were
selected and their pages concatenate.

*Verified:* uploaded through the browser, `202`; and the F2 journey in
`e2e/live-loop.spec.ts` asserts it against the real API, which is the only layer
that can see this class of bug (`docs/handover.md:107-110` predicted it, and
F1-review found the same defect in `/sources`).

**Confirm wrote nothing and reported success (P0-2).** The upload screen never
sent `sheet_id`, so every `Detection` got no exercise, `confirm_scan` skipped all
of them, and the scan flipped to `confirmed` while the teacher read "Résultats
enregistrés". `sheet_id` is now **required** at upload — without it the pipeline
has no answer key, no per-copy pagination and no class to check UIDs against, so
it can read every mark and grade nothing — and the upload screen asks for it.
`confirm_scan` additionally refuses a pile where no reading matched its sheet,
rather than reporting a save.

*Verified:* `test_a_scan_that_can_grade_nothing_is_refused_at_confirm`, and a
25-student round trip through the browser that produced 100 attempts.

**A differentiated copy was graded against the wrong exercises (P0-3).**
`_persist_page` paired a detection by `sheet_items[number - 1]` — the *sheet's*
list indexed by the *copy's* number. For an adaptive sheet `sheet.items` is the
union over the class while each instance prints its own subset, so a student who
answered both their items correctly scored 0/2, at `outcome=detected` and full
confidence, one attempt filed against an exercise never printed for them. The
exercise is now resolved through that copy's own pagination and **stored on the
row** (`Detection.exercise_id`, `printed_number`) rather than re-derived from a
position.

*Verified:* `test_a_differentiated_copy_is_graded_against_its_own_items`.

**One unreadable page shifted every copy behind it (P0-4).**
`_page_within_copy` used `scan_page_index % len(pages)` — the global index in the
upload — although the UID had already been decoded for that page. A 5-item MCQ
sheet paginates to three physical pages, so multi-page copies are the norm; a
lens-cap frame at the front of a 6-page pile graded **8 of 10 attempts wrong**
for students who had answered everything correctly. Pages are now counted per
decoded UID, and a page whose code did not decode consumes nobody's slot.

*Verified:* `test_an_unreadable_page_does_not_shift_the_copies_behind_it`.

---

## The detector's two real defects

**A partially-filled second bubble was silently accepted at confidence 1.0000.**
`detect_item` reached `MULTIPLE` only when `second >= FILL_MARKED and margin <
MARGIN_CONFIDENT`; a runner-up at fill 0.6637 — 1.9× `FILL_MARKED`, unmistakably
a mark — cleared the margin and the item was reported as a single confident
answer. A student who fills B and half-fills C got no review. The margin no
longer takes part: any second bubble above `FILL_MARKED` is ambiguous, which is
what D5 says.

*Verified:* swept the second mark's radius 0.40 → 0.75; `MULTIPLE` from fill
0.398 upward, and the clean/`phone_photo`/`copier` pages still read 16/16.

**`quality` was computed, stored, and never gated on.** `register` fits a
homography onto any four dark marks. With all four fiducials erased it found
four cells of the UID grid, "registered" at quality 0.2856 and emitted nine wrong
answers at confidence up to 1.0000 — the bubble confidences cannot see this,
because they only measure ink at the coordinates they were handed. `MIN_QUALITY
= 0.55` now rejects it: a real page scores >0.99 flat, 0.92 through a phone
photo and 0.62 at the steepest perspective that still registers.

*Verified:* 0/1/2/4 fiducials erased → refused with the quality in the message;
every legitimate degradation still registers (worst case 0.6165).

---

## The rest

**`layout_version` is honoured.** It is pinned onto the `Scan` at upload from the
sheet, threaded into `process_page`, and a mismatch refuses the page instead of
sampling the wrong coordinates and returning plausible answers. Only `v1` exists,
so this is the promise at `layout.py:12` becoming true before it is needed.

**The review screen shows the scanned page.** `ScanReviewOverlay` was built,
exported and imported by nothing. Two things had to be fixed before it could be
wired: the stored image was the *raw upload* (still rotated), so
`reg.canonical` is stored instead; and the detector's `u,v` are relative to the
**fiducial frame**, which is not the page — 18–192 mm of a 210 mm sheet — so the
component now takes an explicit `frame` and has no default, because guessing is
what put every box one to two bubble pitches out.

*Verified:* measured the rendered boxes against `layout.py`'s printed bubble
centres — **0.01 mm**.

**Manual assignment exists, and makes the page gradeable.** The endpoint, the
hook and the strings all existed and nothing called them; the client also posted
to `/pages/{id}/assign`, which is not a route. There is now a picker, scoped to
the sheet's class (`GET /scans/{id}/students`) — offering the whole school
invites the mis-assignment the checksummed UID grid exists to prevent. Assigning
also **re-reads** the page against that student's copy: until the copy is known
the page is read against the default grid with every reading unpaired, so naming
the student and stopping there produced a screen full of detections that graded
nothing.

**A junk page no longer holds the pile hostage.** `POST /scans/{id}/pages/{id}/discard`
sets a page aside — the row is kept, confirmation ignores it. Previously the only
way past a blank cover sheet was to attribute it to a real child.

**Foreign-class pages are flagged.** `_resolve_student` matched on school + UID
only. A page whose student is not in the sheet's class is now marked
`wrong_class`, is not detected against this sheet's grid (12 phantom
low-confidence rows per page, for a page that is not ours), and does not block
confirmation.

**Re-scanning corrects the record instead of doubling it.** `confirm_scan`
supersedes the previous attempt for the same (student, exercise, sheet); the
unique constraint is the backstop. Mastery is a weighted mean, so a duplicate did
not move the score much but silently doubled that lesson's weight.

**The machine's reading survives the override.** `machine_index`,
`machine_outcome` and `machine_confidence` are written once at detection time and
never updated; the review screen shows what the scanner read next to what the
teacher chose.

**Ungradeable items are counted, not dropped in silence.** `items_skipped` is
reported and shown: an item that went in on paper and comes out with no record is
worth saying.

**A corrupt upload fails loudly.** `process_scan` returned a result dict on a
decode failure, so the job recorded `succeeded` at progress 1.0 while the scan
sat in `FAILED` — a green tick and an empty review page. It raises now, and the
message names the file rather than quoting PyMuPDF.

**Per-page progress is visible.** The worker always reported it; nothing read it.
`ScanOut.job_id` carries the job through to the review screen, which polls it and
shows "page 15 of 28" — and `useScan` polls until the scan reaches a terminal
state, so a processing scan no longer looks like a finished empty one.

**Smaller things.** Rows show the printed number, the statement and the options
with the glyphs the student saw (V/F, not A/B) · a true/false item cannot be
corrected to option 3 · `detected_bool` is only set on true/false items · "N"
jumps to the next uncertain item · override targets measure 50×44 px on a phone
(were 33×36) · the overlay's hit areas stay inside the 8 mm bubble pitch, because
44 px squares made each bubble swallow its neighbour's clicks · a badge no longer
holds a full sentence, which pushed the phone layout 138 px sideways ·
`register_grader()` is public, so the free-text seam is not a private name.

**The seed can now detect a grading bug.** Every MCQ answered option 0, so a
pipeline that always guessed "A" scored 100 % against the demo data. Options are
rotated so the correct answer lands across all four positions — same options,
same correct answer, different place.

---

## What was run

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q   # 391 passed
.venv/bin/ruff check apps/api                                      # clean
.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy # clean, 67 files
pnpm typecheck && pnpm lint && pnpm i18n:check                      # clean, 287 keys in sync
pnpm exec playwright test --project=desktop --project=phone         # 45 passed
ALPPY_LIVE_API=… ALPPY_LIVE_WEB=… pnpm exec playwright test --project=live  # 4 passed
docker compose up -d                                                # migration 0003 applied
```

Against the live stack: the F1-generated `blank.pdf` for 7B filled
programmatically at `layout.bubble_centre_mm`, uploaded, processed
(`page 1 of 50` … `page 50 of 50`), reviewed, confirmed — **12/12 detections
correct, 100 attempts, 0 duplicates on re-upload**. A 28-page mixed batch
(25 own copies, 2 from another class, 1 blank) scored **25 assigned, 2 flagged,
1 unreadable**, refused confirmation until the blank was set aside, then
confirmed. Screenshots in [`screenshots/F2-after/`](screenshots/F2-after/).

## The second pass

Four things the first pass reported as done were not, and three the first pass
deferred turned out to be fixable properly rather than by tuning.

**Shown on a review row: the answer key.** `DetectionOut.answer_index` — for a
true/false item derived from `answer_bool`, since bubble 0 is "true" in every
sheet language. Marked in the option list with a word, not a colour.

**No raw API string reaches a teacher.** `client.ts` already said `message` is
"for the console, never for the teacher"; the upload screen rendered it anyway.
There is now an `errors.code` catalogue in all three locales and one
`apiErrorMessage()` switch. The two 409s a teacher can actually resolve —
"pages belong to nobody" and "none of these match the sheet" — were given their
own codes (`scan_pages_unassigned`, `scan_matches_no_sheet`) rather than sharing
a generic string with every other conflict, because each is resolved
differently and the message is the instruction.

**`LOW_CONFIDENCE` is generated, not typed.** `SCAN_THRESHOLDS` now rides the
same `scripts/export-layout.py` path as the geometry, and CI already fails on a
stale generated file. The review screen mirrored the detector's threshold with a
`0.65` typed into a React component, three files and one language away.

**`scan.error` survives confirmation.** A batch that came back with a page it
could not read stays one.

**Rotation: ~7° → past 30°, and no longer depends on framing.** This was not a
tuned constant, it was a wrong measurement. Squareness and solidity were taken
from `cv2.boundingRect` — an *axis-aligned* box, whose area grows as
`(cos t + sin t)^2` as the page turns, so extent fell below the 0.72 gate at
about 10° and a real fiducial was rejected for the crime of being tilted.
`cv2.minAreaRect` measures the contour's own rectangle and is rotation-invariant,
which is what "is this a solid square" always meant. The aspect band widened to
0.55–1.8 to match: under the steepest keystone the pipeline registers, a square
genuinely *is* a rectangle. The area floor was loosened because it is derived
from the whole image, which is why a photo with desk visible around the sheet
behaved differently from a tight crop.

*Verified:* 360 page/condition combinations — **0 wrong UIDs, 0 wrong items**;
every degradation still exact including `perspective 0.220`, which the first
attempt at this had silently regressed; the quality gate still refuses 1, 2 and
4 erased fiducials; and 40 solid decoy squares scattered over a page do not
displace a real fiducial. Locked in by `test_a_crooked_page_still_registers`
(±8/15/25°) and `test_decoy_squares_do_not_displace_a_real_fiducial`.

**HEIC is read.** It needed a decode path, and now has one: `pillow-heif`, tried
only after OpenCV declines, plus ISO-BMFF brand sniffing (`ftyp` + `heic`,
`mif1`, `avif`, …) so claiming the type is not the same as being it. The
allowlist lives in `.env`, which is why changing the default alone did nothing.

*Verified:* a synthetic page put through `phone_photo`, saved as real HEIC and
uploaded to the running stack — decoded, registered, UID `7B_04` read, both
answers correct, confirmed.

**The faint-mark band has tests.** `detector.py:374-378` — the branch between
"clearly blank" and "clearly marked", which the whole safety design rests on —
was reached by nothing. `test_a_faint_mark_is_read_but_flagged` puts a tick
rather than a filled bubble on a page of fifteen firm marks, so the page-level
mostly-blank rule cannot mask it, and asserts the mark is *read* and *flagged*.

## Still open

- **No real paper.** `layout.py` matches the generated PDF to 0.14 mm and the
  loop is exact on it — including through a real HEIC — but nothing has been
  printed, photocopied and photographed. Every accuracy figure means "the
  geometry and the logic are right", not "this works in a classroom". This is
  the only F2 finding still open, and it cannot be closed from here.
