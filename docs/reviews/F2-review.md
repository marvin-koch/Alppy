# F2 — Scan and correction (MCQ + true/false) · independent review

Reviewer: independent agent · 2026-09-06 · commit `1ea7ee6` on `main`.
Stack: `docker compose` up (`alppy-{web,api,worker,postgres,redis,minio}-1`), plus the repo `.venv`
(Python 3.11.11, OpenCV 5.0.0, PyMuPDF 1.28.2) for pipeline-level reproductions.

Read first, in order: `CLAUDE.md`, `DESIGN.md`, `docs/plan.md`, `docs/decisions-log.md`, then
`apps/api/alppy/scan/**`, `apps/api/alppy/services/scan_{processing,service}.py`,
`apps/api/alppy/api/v1/scans.py`, `apps/api/alppy/sheets/{layout,pagination,uid_code}.py`,
`packages/ui/src/components/domain/{ScanReviewOverlay,ConfidenceBar}.tsx`,
`apps/web/src/app/[locale]/scans/**`, and `apps/api/tests/`.

---

> **Resolved.** Every P0 and P1 below, and most of the P2s, were fixed and
> re-verified — see [`F2-fixes.md`](F2-fixes.md). This document is kept as the
> record of what was found and how, not as the current state of the code.

## 1. Verdict

**FAIL** — 4 P0 · 13 P1 · 11 P2 · 5 P3.

The detector is the best-engineered thing in this repository and it holds up: across 630
degradation runs and a real generated PDF it read **8 640 / 8 640 items and 0 wrong UIDs**. What
fails is everything between the detector and a graded attempt. The scan upload is impossible from
the browser (the client posts `files`, the API requires `file`), and on the API path a scan can be
confirmed while silently writing either **no attempts at all** or attempts **graded against the
wrong exercises**. The review screen never shows the scanned page, and there is no way to assign a
page whose code did not read — so one bad photo in a pile permanently blocks the other 27 copies.

The root cause is narrow and nameable: **`apps/api/alppy/services/scan_processing.py` has 0 %
coverage and is imported by no test.** Every P0 lives in that file or in the untested web contract.
`docs/handover.md:15` records this milestone as "Done, verified against synthetic degradation
only"; that is accurate about the detector and wrong about the phase.
## 2. What I ran

### Stack and gates
```bash
docker ps                                                   # all six containers up
curl -c jar -X POST localhost:8000/api/v1/auth/login \
  -d '{"email":"demo@alppy.ch","password":"alppy-demo-2026"}'          # 200
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests -q       # 300 passed, 17.8s, 0 skips
.venv/bin/ruff check apps/api                                          # All checks passed!
.venv/bin/mypy --config-file apps/api/pyproject.toml apps/api/alppy    # no issues, 67 files
pnpm i18n:check                                                        # ok — 261 keys in sync
grep -rnE "#[0-9a-fA-F]{3,8}\b|rgb\(" apps/ packages/ --include='*.tsx' \
     --include='*.ts' --include='*.css' | grep -v node_modules         # 1 hit, a comment
curl localhost:8000/api/v1/openapi.json                                # 36 paths, 6 of them scans
```
Coverage was measured with the stdlib `trace` module — pytest-cov is not installed and I installed
nothing. `alppy/scan/detector.py` 92.6 %, `grading.py` 97.6 %, **`services/scan_processing.py` 0 %**.

### The full loop on the real F1-generated PDF
Created a 5-item sheet (2 MCQ, 2 true/false, 1 open) for 7B, rendered it
(`POST /sheets/{id}/render` → 36-page `blank.pdf`), extracted the **printed** bubble centres from
the PDF drawing operators and checked them against `L.bubble_centre_mm()` (max deviation 0.14 mm),
then filled known answers into the real PDF for six students — one all-correct, one all-wrong, one
mixed, one with a blank item, one double-marked, one lightly filled — and pushed it through
`POST /scans` → worker → `GET /scans/{id}/detections` → `PATCH …/detections/{id}` →
`POST …/confirm`, verifying every `attempt` row against ground truth in Postgres. Repeated at
25 students. Re-ran three pages through `synthetic.phone_photo` and `copier` and uploaded those.

### Synthetic degradation sweep
45 pages (UIDs `7B_01`–`7B_28`, `7B_99`, two-letter class `11AB_15`; mixed 2- and 4-option items;
pencil 0.35 / 0.60 / 0.90) × 14 conditions = **630 `process_page` calls, 10 080 items**: clean,
rotate +3/+7/−5°, perspective at `s` = 0.045 / 0.100 / 0.150 / 0.220 / 0.281 (calibrated against a
pinhole model — `s=0.281` ≈ a 20° tilt at 350 mm), JPEG q40, 150 dpi, shadow gradient, and the
`phone_photo()` / `copier()` presets. Plus a 13 824-item stress population (pencil 0.16→0.70 with
mark jitter) built specifically to get a confidence-separation number, because the main sweep
produced no errors to separate.

### Adversarial probes
Empty page and a blank-ratio sweep (the D7 rule fires at exactly 10/16) · double marks varied by
**darkness** and by **area** · erase-then-remark across 12 residue strengths, before and after
photocopying · marks offset 1–5 mm from the bubble centre · one-item, zero-item and free-text-only
sheets · pages with 0, 1, 2 and 4 fiducials erased · an answer grid shifted 0–8.5 mm to simulate a
layout-version change · rotation on clipped and padded canvases at three padding fractions.

### Reproductions I wrote (scratchpad; run against the repo's own SQLite fixtures)
`PYTHONPATH=apps/api:apps/api/tests .venv/bin/python -m pytest <file> -q -s`. These drive the
**real** `scan_processing.process_scan` and `scan_service.confirm_scan`, not mocks.

| script | what it exercises |
|---|---|
| `test_repro_nosheet.py` | the upload path the web UI actually takes (`sheet_id` absent) |
| `test_repro_itemplan.py` | a copy whose `item_plan` differs from `sheet.items` (adaptive shape) |
| `test_repro_multipage.py` | multi-page copies with one unreadable page in the pile |
| `test_repro_wrongclass.py` | a page belonging to another class of the same school |
| `test_repro_idempotency.py` | the same pile uploaded twice, and confirming twice |

### Mixed batch, upload validation, timing
A 28-page PDF (25 × 7B, 2 × a second class `8A` created through the API, 1 blank A4), with
`GET /jobs/{id}` polled every 0.5 s. `POST /scans` probed with PNG, JPEG, 28-page PDF, **real HEIC
bytes** (`sips -s format heic`), JPEG relabelled HEIC, `.txt`, `.zip`, 50 MB + 1 byte, exactly
50 MB, 0 bytes, and a corrupt PDF. Timing taken from worker logs and job timestamps.

### Driven in a real browser
Chromium via the repo's Playwright, against the running stack: login → nav → `/fr/scans/new` →
upload (network intercepted with `postDataBuffer()`) → `/fr/scans/{id}` → override → reload →
confirm → reload. Tab-order walk logging `document.activeElement`. Screenshots at 1440×900 and
390×844 in fr/de/en, and in all seven states of `data-theme` / `data-contrast` / `data-motion` /
`data-calm`, with WCAG contrast ratios computed in-page. Saved to
`docs/reviews/screenshots/F2/` (`01-home`, `02-upload`, `10-review-desktop`, `11-confidencebar`,
`12-after-override`, `13-after-reload`, `14-nouid-page`, `20/21-processing-*`, `30-32-focus-*`,
`40-42-confirmed-*`, `50-51-theme-*`, `60-61-*-{desktop,phone}`, `70-i18n-{fr,de,en}-*`).

## 3. Requirement trace

| # | Requirement | How verified | Result | Evidence |
|---|---|---|---|---|
| R1a | Upload accepts multi-page PDF, JPEG, PNG | `curl -F "file=@…"` for each against the running API; PDF rasterised at 200 dpi by `_decode_pages` | **OK** (API) / **FAIL** (UI) | 202 on all three; from the browser every upload is 422 — P0-1 |
| R1b | HEIC-if-claimed | `config.py:71-76` allowlist; `read_upload` rejects on declared type | **FAIL** | real HEIC bytes (`sips -s format heic`) → 415 `"content type 'image/heic' is not accepted"`. P2-6 |
| R1c | Rejects oversized/unsupported with a clear message | `read_upload` (`deps.py:236-278`): declared type, magic bytes, streamed size cap | **OK** | 415 `unsupported_media_type`, 413 `payload_too_large`, 422 empty — all structured, no stack traces |
| R1d | Processing runs in the worker | `worker/tasks.py:154-170` → `scan_processing.process_scan`; `POST /scans` only stores + queues | **OK** | `scans.py:50-70` returns 202 without detecting |
| R1e | Per-page progress | `on_progress` per page (`scan_processing.py:242-246`) reaches `Job`; no client reads it | **FAIL** | neither scan screen imports `useJob`; `useScan` has no `refetchInterval`. P1-6 |
| R2a | Finds four fiducials, deskews, registers | 630 degradation runs + the real PDF path + damaged-fiducial probes | **OK, with a hole** | 100 % registration to ±5° / perspective `s=0.220`; but `process_page` never gates on `quality` — with all four fiducials erased it still "registers" at quality 0.2856 and emits 9 wrong items at confidence 1.0000. P1-10 |
| R2b | A page from a different `layout_version` is detected as such | traced `scan_processing.py:202-226` and `detector.py`; `grep layout_version apps/api/alppy/scan/` | **FAIL** | `sheet.layout_version` loaded, never read; `process_page` has no version parameter. P1-4 |
| R3a | UID read from the printed grid | 32-bit CRC-8 grid; every 1- and 2-bit error rejected (`test_uid_code.py:37-53`) | **OK** | decode failure routes to manual, never to a different student |
| R3b | Fallback to manual assignment when confidence is low | endpoint + service + hook + strings all exist | **FAIL** | no UI control calls them; `grep useAssignScanPage apps/web/src` → definition only. P1-2 |
| R3c | Manual assignment lists only students of the sheet's class | `assign_page_student` (`scan_service.py:303-305`) | **FAIL** | scoped to `school_id`, not the class; and there is no UI to scope. P1-2 |
| R4a | Per-item confidence; empty, erased-then-remarked and off-bubble marks | ran each case myself across a parameter sweep | **OK** | off-centre marks fall to "no answer, low confidence" by 3 mm and never read as a neighbour; the all-blank page flags all 16 (D7's rule fires at exactly 10/16); erase residue → firm mark chosen, or `MULTIPLE` |
| R4b | A double-marked item is never a silent wrong answer at high confidence | swept the runner-up mark's **area**, not just its darkness | **FAIL** | a runner-up at fill 0.6637 — 1.9× `FILL_MARKED` — is discarded and the item reported `detected` at **confidence 1.0000**. P1-9 |
| R5a | Grading correct per item against the answer key | `test_grading.py` (10 tests) + my end-to-end repro B | **OK** *for a plain class sheet* | 2/2 attempts correct with `sheet_id` set |
| R5b | Correct for a differentiated copy | `test_repro_itemplan.py` | **FAIL** | graded against the sheet's union list — P0-3 |
| R5c | Aggregated per competency | `confirm_scan` → `recompute_for_students`; `test_api_scans.py:223` asserts the band moves | **OK** | band `fading` → `ok` |
| R5d | `open` items shown as not auto-graded and never scored | `grading.py:109-115`; `_grade_open` returns `NOT_GRADEABLE`; badge renders `outcome.not_gradeable` | **OK** | `test_grading.py:55`, `test_scan_pipeline.py:126` |
| R6a | Scanned page with detections overlaid at the right coordinates | inspected the review screen and the DOM | **FAIL** | no image, no overlay; `ScanReviewOverlay` unused, and its frame does not match the detector's. P1-1 |
| R6b | `ConfidenceBar` per item | review screen `page.tsx:155-160` | **OK** | rendered per detection with the 0.65 threshold marker |
| R6c | Low-confidence items surfaced first | `page.tsx:33-38` sorts ascending by confidence | **OK** | but see R6a — there is nothing to look at beside the bar |
| R6d | One-click override | `SegmentedControl` per row, `PATCH …/detections/{id}` | **OK** | 200, `outcome=corrected`, `confidence=1.0` |
| R6e | Override stored distinct from the detection, both retained | read the row before/after; inspected the `Detection` model | **FAIL** | the machine's reading is overwritten in place; no column holds it. P1-3 |
| R6f | Confirm → attempts written | `test_repro_nosheet.py` A and B | **FAIL** on the UI path | 0 attempts, reported as saved. P0-2 |
| R6g | Re-opening a confirmed scan shows it as confirmed | `GET /scans/{id}` after confirm; button `disabled={status === 'confirmed'}` | **OK** | status persists as `confirmed` |
| R7a | Uploading the same scan twice does not duplicate attempts | re-posted the identical PDF bytes on the live stack, then `test_repro_idempotency.py` | **FAIL** | attempts 24 → 47; 23 (student, exercise) pairs doubled; no unique constraint on `attempt`, no upload digest. P1-8 |
| R7b | Confirming twice does not double-count | same script | **OK** | second confirm → 409 `scan is already confirmed` |
| R8 | A grader interface exists where free text could be registered; none implemented | read `grading.py`; `ItemGrader` Protocol + `_GRADERS` dispatch | **OK, with a caveat** | behaviour correct; the registry is private with no registration function. P3-1 |
| R9 | Vision fallback off by default, sends only page + UID, logged | grepped the whole scan path for any model call | **OK (vacuously)** | there is no vision or LLM fallback at all; scan never imports `alppy.ai`; `model_call` empty after my runs; no student name appears in any scan schema |
## 4. Findings

### P0

#### P0-1 · The scan upload cannot be performed from the UI: the client posts the wrong field name
`apps/web/src/lib/api/endpoints.ts:136` builds the multipart body with `formData.append('files', file)`.
`apps/api/alppy/api/v1/scans.py:57` declares `file: Annotated[UploadFile, File()]` — singular.

Reproduced against the running API:
```
POST /api/v1/scans -F "files=@probe.png;type=image/png"
→ 422 {"error":{"code":"validation_error","message":"request body failed validation",
       "details":{"errors":[{"loc":["body","file"],"msg":"Field required","type":"missing"}]}}}

POST /api/v1/scans -F "file=@probe.png;type=image/png"
→ 202 {"id":"902c6e36-7587-4569-864d-6a78d0266a3a","status":"uploaded","pages":[]}
```
**Expected:** dropping copies on `/scans/new` starts processing.
**Observed:** every upload from the browser is rejected with 422 before it reaches the worker.
The F2 core loop has no entry point in the product.

This is the exact bug class the handover predicted at `docs/handover.md:107-110`: *"the e2e suite
runs against the fixture layer, not the API… it cannot catch a contract drift between
`alppy/schemas` and `apps/web/src/lib/api/types.ts`."* The same defect was found in F1 for
`/sources` (F1-review P0-3) and fixed there (`endpoints.ts:104-109` now sends `subject_id`);
`/scans` was never re-checked.

*Fix direction:* send `file` (and loop the picker's multiple files into separate requests, since
the endpoint takes one file per scan), and generate the client from the served OpenAPI document as
`docs/plan.md` §4 already requires.

#### P0-2 · The UI never sends `sheet_id`, so confirming a scan writes zero attempts and says it saved
`apps/web/src/app/[locale]/scans/new/page.tsx:19` calls `upload.mutate({ files })` with no
`sheetId`, and there is no sheet picker on the screen. `sheet_id` is optional on the endpoint
(`scans.py:58`). With it absent, `_pages_by_uid` returns `{}` (`scan_processing.py:85-86`), every
`Detection` is written with `sheet_item_id = None` (`scan_processing.py:152-155`), and at confirm
`_exercise_for_detection` returns `None` so every detection is skipped
(`scan_service.py:249-252`).

Reproduced (`test_repro_nosheet.py`) on a 5-item sheet where the student answered **all five
correctly**:
```
########## A: sheet_id=None  (what the web UI sends) ##########
  sheet has 5 items; detections created: 16
  detections with a sheet_item_id: 0
  page.detected_uid=7B_01 student_id set: True
  outcomes: {'detected': 5, 'low_confidence': 11}
  items the review screen shows as needing a human: 11 of 16
  CONFIRM -> attempts_created=0 students_affected=0 competencies_updated=0
  attempts in db: 0
  scan status: confirmed

########## B: sheet_id set (only reachable via the API) ##########
  detections created: 2  with sheet_item_id: 2
  CONFIRM -> attempts_created=2 students_affected=1 competencies_updated=1
  all correct? [True, True]
```
**Expected:** confirming a correctly-read page produces attempts and moves the mastery matrix.
**Observed:** the scan flips to `confirmed`, the UI renders `scans.confirmed` ("Résultats
enregistrés"), and nothing was graded. The teacher is told their marking is saved when it was
discarded. Note also the 16-vs-5 detections: without a sheet the pipeline probes the full
16×4 default grid (`scan_processing.py:208`), so 11 rows correspond to bubbles that were never
printed, and `_flag_suspicious_blanks` then downgrades them all to low confidence — the review
screen opens with 11 phantom items demanding attention.

*Fix direction:* require `sheet_id` on upload and add a sheet picker; refuse to confirm a scan
that produced no gradeable detection rather than reporting success.

#### P0-3 · A differentiated copy is graded against the wrong exercises
`scan_processing.py:151-155` pairs a detection with a sheet item by
`sheet_items[placed_item.number - 1]` — it indexes the **sheet's** ordered item list by the
**copy's** printed item number. For a plain class sheet those coincide. For an adaptive sheet they
do not: `create_adaptive_sheet` (`sheet_service.py:186-189`) makes `sheet.items` the *union* over
the class while each `SheetInstance.item_plan` is that student's own ordered subset, and
`_pages_by_uid` (`scan_processing.py:70-88`) correctly paginates the per-student plan.

Reproduced (`test_repro_itemplan.py`). `sheet.items = [E1, E2, E3]`; this student's `item_plan`
is `[E3, E1]`; the student marks **both of their own items correctly**:
```
--- detections (page-local item_index -> exercise it was paired with) ---
  item_index=0 detected_index=2 outcome=detected -> sheet_item E1
  item_index=1 detected_index=0 outcome=detected -> sheet_item E2

  expected pairing: {0: 'E3', 1: 'E1'}
  actual   pairing: {0: 'E1', 1: 'E2'}

--- attempts written: 2 ---
  exercise=E1 correct=False score=0.0
  exercise=E2 correct=False score=0.0
```
**Expected:** 2 attempts, both correct.
**Observed:** 2 attempts, both wrong, at `outcome=detected` with full confidence — and one of them
(E2) is an exercise that was never printed on this student's copy. Nothing in the review UI can
show this, because the review UI shows no statements. The wrong scores then feed
`recompute_for_students` and the mastery matrix.

*Fix direction:* resolve the sheet item through the copy's own `item_plan` (the instance already
resolved for this UID) rather than by position in `sheet.items`; store the resolved
`exercise_id` on the detection so the pairing is auditable.

#### P0-4 · One unreadable page shifts every copy behind it in the pile
`_page_within_copy` (`scan_processing.py:263-272`) decides which page of a student's copy an image
is with `scan_page_index % len(pages)` — the **global** index in the upload, not a per-UID counter,
even though the UID has already been decoded for that page. Multi-page copies are the normal case,
not an edge case: a 5-item MCQ sheet already paginates to three physical pages.

Reproduced (`test_repro_multipage.py`), 2 students × 3 pages, everyone answering everything
correctly:
```
  a 5-item MCQ sheet paginates to 3 physical pages ([2, 2, 1] items each)

  --- perfectly ordered pile ---
      confirm: attempts_created=10 students_affected=2 competencies_updated=2
      attempts written: 10; graded WRONG: 0

  --- same pile + ONE unreadable page at the front ---
      confirm REFUSED: ApiError: every scanned page must be assigned to a student before confirming
  (after assigning that junk page by hand, the documented fallback:)
      confirm: attempts_created=10 students_affected=2 competencies_updated=2
      attempts written: 10; graded WRONG: 8
```
**Expected:** a bad photo in the pile costs that page and nothing else.
**Observed:** either the whole scan deadlocks (see P1-7), or — once the teacher clears the deadlock
the only way the API allows — 8 of 10 attempts are graded wrong for students who answered
everything correctly. A lens-cap frame, a cover sheet or a re-shot page is enough to trigger it.

*Fix direction:* count pages per decoded UID instead of using the global index, and treat a page
whose UID did not decode as belonging to no copy rather than consuming a slot.
### P1

#### P1-1 · The review screen never shows the scanned page; `ScanReviewOverlay` is dead code
R6 asks for "the scanned page with detections overlaid at the right coordinates". The review
screen (`apps/web/src/app/[locale]/scans/[scanId]/page.tsx`) renders a `Card` per page containing a
list of `Panel` rows — no `<img>`, no overlay. `ScanReviewOverlay` is exported
(`packages/ui/src/components/domain/index.ts:21`) and imported by nothing:
```
grep -rn "ScanReviewOverlay" apps/web/src        →  no matches
page.locator('[role="group"]').count()           →  0
main img                                         →  []
```
Confirmed in a real Chromium session: the review screen renders no `<img>` and no mark boxes; the
rendered HTML contains no `data-state` and no `data-low-confidence`.
The API already serves everything the overlay needs — `ScanPageOut.image_url`
(`schemas/__init__.py:290`) and `DetectionOut.bubble_boxes` (`:277`) — so this is an unwired
component, not a missing capability.

Two things must be fixed together before it can be wired, both of which I measured:

1. **Coordinate frames do not match.** The detector emits `u,v` normalised to the *fiducial
   frame* (`detector.py:340-349` via `layout.BubbleSlot.u/v`), which spans 18–192 mm of a 210 mm
   page. The overlay positions boxes as percentages of the *image box* (`ScanReviewOverlay.tsx:97`
   `absolute inset-0`, `:117` `left: pct(mark.u)`). On a perfectly flat page:
```
   item0  optA : real (19.29%,70.20%) vs overlay (12.93%,72.99%) → off 13.3 mm x,  8.3 mm y
   item7  optD : real (30.71%,90.24%) vs overlay (26.72%,95.79%) → off  8.4 mm x, 16.5 mm y
   item15 optD : real (72.62%,90.24%) vs overlay (77.30%,95.79%) → off  9.8 mm x, 16.5 mm y
   (bubble diameter 5 mm, bubble pitch 8 mm)
```
2. **The stored image is the raw upload, not the registered one.** `scan_processing.py:227` writes
   `_store_page_image(storage, key, image)` — the decoded original, still rotated and
   perspective-distorted. `reg.canonical`, the deskewed page the coordinates actually describe, is
   computed (`detector.py:211-215`) and thrown away.

*Fix direction:* store `reg.canonical` as the review image and give the overlay the frame inset,
or emit page-normalised coordinates; then render the overlay on the review screen.

#### P1-2 · There is no manual student-assignment UI
R3 requires a manual fallback "listing only students of the sheet's class". The pieces all exist
and none are connected: `PATCH /scans/{id}/pages/{page_id}` (`scans.py:107`),
`assign_page_student` (`scan_service.py:287`), the `useAssignScanPage` hook (`queries.ts:260`),
and the translated strings `scans.assignManually` / `scans.chooseStudent` in all three catalogues.
```
grep -rn "useAssignScanPage" apps/web/src        →  only its own definition
main select, main [role="combobox"], [role="listbox"]  →  0
curl -X POST /api/v1/scans/{id}/pages/{pid}/assign     →  HTTP 404 not_found
```
Driven in the browser on a scan whose UID grid I blanked: the page renders "Élève non identifié"
with no control of any kind, reports **"rien à vérifier"**, and leaves Confirm enabled — which then
409s server-side with no error shown, because `useConfirmScan` has no `onError` path.
When the UID does not decode the screen renders `scans.notIdentified` ("Élève non identifié",
`page.tsx:92`) and offers no control at all — and since `confirm_scan` refuses while any page is
unassigned (`scan_service.py:225-230`), the teacher is left with a scan they can neither assign nor
confirm. Note also that `assign_page_student` scopes candidates to the *school*
(`scan_service.py:303-305`), not to the sheet's class, so the requirement's "only students of the
sheet's class" is not enforced server-side either.

Separately, the client calls the wrong route for this endpoint —
`endpoints.ts:152` posts to `/scans/{id}/pages/{id}/assign` while the API declares `PATCH
/scans/{scan_id}/pages/{page_id}`. Latent only because nothing calls it.

#### P1-3 · A teacher correction overwrites the machine's reading instead of being stored beside it
R6 requires the override to be "stored as a teacher correction distinct from the detection (both
retained)". `correct_detection` (`scan_service.py:169-180`) assigns over the same columns:
```python
detection.detected_index = payload.detected_index
detection.detected_bool  = ...
detection.outcome        = DetectionOutcome.CORRECTED
detection.confidence     = 1.0
```
Observed on the live stack, the same row before and after `PATCH … {"detected_index":0}` → 200:
```
BEFORE                                  AFTER
detected_index  | 3                      detected_index  | 0
detected_bool   | f                      detected_bool   |
outcome         | DETECTED               outcome         | CORRECTED
confidence      | 1                      confidence      | 1
fill_ratios     | [0,0,0,0.97867]        fill_ratios     | [0,0,0,0.97867]
corrected_by_id |                        corrected_by_id | 5c143f7f-…
corrected_at    |                        corrected_at    | 2026-09-06 10:23:38+00
```
On an ambiguous row the machine's `outcome=MULTIPLE` and `confidence=0.4937264742785445` were
likewise erased. `\d detection` shows no `original_*` column and `\dt` lists no correction or
history table among the 25 tables.

The `Detection` model (`models/__init__.py:453-479`) has no column holding the original reading —
`corrected_by_id` and `corrected_at` record *who* and *when*, but not *what the machine said*. The
module docstring claims the opposite (`scan_service.py:9-10`: "never as a silent overwrite of the
machine's reading — the original detection stays in the row for audit"). Only `fill_ratios`
survives, and the outcome and confidence that justified surfacing the item are gone.

*Fix direction:* add `machine_index` / `machine_outcome` / `machine_confidence` columns written
once at detection time and never updated, or a separate `DetectionCorrection` row.

#### P1-4 · `layout_version` is loaded and never read: a mismatched page is silently misread
R2 requires that a page from a different `layout_version` is detected as such. It is not, anywhere.
`process_page` (`detector.py:427`) takes `(image, option_counts)` — there is no version parameter
to pass. `scan_processing.py:202-206` loads the `Sheet` row that carries `sheet.layout_version` and
then computes geometry from the current module constants (`:208`, `:216`, `:224`) without ever
reading it. `grep -rn layout_version apps/api/alppy/scan/` returns nothing.

Only `"v1"` exists today (`layout.py:23`), so there is no live misread — but there is also no
mechanism to *hold* an old layout's constants, so the promise at `layout.py:12` ("Sheets store the
version they were printed with so old scans keep working") has no implementation behind it. The
failure mode when v2 lands is not an error, it is plausible-looking wrong answers.

*Fix direction:* thread the sheet's version into `process_page` and refuse (or route to manual)
when it is not the version the detector implements; keep versioned geometry modules.

#### P1-5 · A page from another class is accepted and not flagged
The mixed-batch procedure expects foreign-class pages to be flagged. `_resolve_student`
(`scan_processing.py:91-98`) matches on `school_id` + `uid` only — no class, no sheet.

Reproduced twice — in the fixture harness (`test_repro_wrongclass.py`) and on the live stack with
the full 28-page mixed batch (25 × 7B, 2 × 8A, 1 blank). The live run:
```
 page | reg | detected_uid | uid_conf | assigned | class | instance | registration_meta
    8 |  t  | 8A_01        |  0.9646  | 8A_01    | 8A    |    f     | {"error":null,"quality":0.999,…}
   17 |  t  | 8A_02        |  0.9646  | 8A_02    | 8A    |    f     | {"error":null,"quality":0.999,…}
   22 |  f  |              |  0.0000  |          |       |    f     | {"error":"found 0 fiducial candidates, need 4",…}
```
Scored against the brief: **25 assigned ✓ · 1 unreadable flagged ✓ · 2 foreign-class pages NOT
flagged ✗.** `uid_confidence` is identical to a correct page and `registration_meta.error` is null.
The only trace is `sheet_instance_id IS NULL`, which is not a flag, is also null for a genuinely
unidentified page, and is surfaced nowhere. Each foreign page also dumps **12 phantom
`LOW_CONFIDENCE` detections** into the review queue. Grades are not corrupted — but by luck, not
design: with no `SheetInstance` the detections get no `sheet_item_id` and `confirm_scan` skips them
(verified: 0 attempts, 0 mastery snapshots for 8A).

The smaller fixture repro, for the same conclusion:
```
  page_index | detected_uid | student assigned | detections | flagged?
      0      |   7B_01      |      yes         |      2     | {'skew_deg': 0.0, 'quality': 1.0, 'error': None}
      1      |   9A_04      |      yes         |     16     | {'skew_deg': 0.0, 'quality': 1.0, 'error': None}

  confirm -> attempts_created=2 ...   (the 9A page was NOT refused and NOT flagged)
```
**Expected:** flagged as belonging to another class.
**Observed:** accepted, assigned to the 9A student, given 16 default-grid detections, and confirmed
without comment. No wrong data is written (there is no `sheet_item_id`), but the teacher is shown a
page headed "Identifié comme 9A_04" among their 7B copies with 16 items to check and no
explanation. `ScanPage` has no column for such a flag.

#### P1-6 · No per-page progress, and the review screen never refreshes
R1 requires per-page progress. The worker does report it — `on_progress((index+1)/len(images),
f"page {index+1} of {len(images)}")` (`scan_processing.py:242-246`) — and `GET /jobs/{id}` serves
it. Nothing consumes it: `useJob` has a `refetchInterval` (`queries.ts:303-308`) and is used by the
sheets and adaptive screens, but neither scan screen imports it. `useScan` (`queries.ts:234-240`)
has no `refetchInterval` either.

The upload screen shows a static `scans.processing` string; the review screen a teacher lands on
after upload shows a scan with `status: "uploaded"` and `pages: []` — an empty page reading
"rien à vérifier" — and never updates until a manual browser reload. Measured in the browser
against an API forced to answer `status: "processing", pages: []`:
```
progressbar count: 0 | role=status count: 0 | extra scan requests in 6s: 0
```
A still-processing scan is visually identical to a finished empty one, with Confirm enabled. The
worker's own progress is fine — polling `GET /jobs/{id}` every 0.5 s during the 28-page batch gave
`0.143 'page 4 of 28'` → `0.536 'page 15 of 28'` → `0.893 'page 25 of 28'` → `1.000 'page 28 of 28'`.

#### P1-7 · An unassignable page deadlocks the whole scan; there is no way to discard a page
`confirm_scan` refuses while any page has no student (`scan_service.py:225-230`) and the API
exposes no endpoint to drop, skip or ignore a page — the paths are `POST /scans`,
`GET /scans/{id}`, `GET /scans/{id}/detections`, `PATCH …/detections/{id}`, `PATCH …/pages/{id}`,
`POST …/confirm`. A blank sheet, a cover page or a failed photo therefore blocks the other 27
copies permanently. Reproduced in `test_repro_multipage.py` (see P0-4): `confirm REFUSED:
every scanned page must be assigned to a student before confirming`, with no UI control to resolve
it (P1-2) and no discard route. The only escape the API offers is to misattribute the junk page to
a real student — which is what triggers P0-4's mis-grading.

#### P1-8 · Uploading the same pile twice doubles every attempt
R7 requires that uploading the same scan twice does not create duplicate attempts. Confirming the
same scan twice is correctly refused; re-uploading is not deduplicated at all, and `Attempt` has no
unique constraint (`models/__init__.py:486-488` declares only
`Index("ix_attempt_student_answered", …)`).

Reproduced on the live stack with the identical `filledA.pdf` bytes and the same `sheet_id`:
```
POST /scans (2nd time)  -> 202     POST /scans/{id}/confirm -> {"attempts_created":23,…}
SELECT count(*) FROM attempt WHERE sheet_id='07704a5e-…';   24  ->  47
SELECT student_id, exercise_id, count(*) … HAVING count(*)>1;  -> 23 rows, every one = 2
\d attempt  ->  no unique constraint;   \d scan  ->  no content-hash column
```
(23 rather than 24 duplicated pairs only because one item stayed `MULTIPLE` and was silently
dropped — see P1-11.) `recompute_for_students` then ran again over the doubled set. Same result in
the fixture harness (`test_repro_idempotency.py`): 2 of 2 pairs doubled, second confirm of the
*same* scan correctly refused with 409.
Mastery is a weighted mean over attempts (`docs/plan.md` §6), so a duplicated sheet does not change
the score much but doubles its weight, making a single lesson count twice against everything else.



#### P1-9 · A partially-filled second bubble is silently discarded and the item reported at confidence 1.0000
This is the one genuine defect in the detector, and it violates R4 and decisions-log D5 head-on
("Two filled bubbles is not information, it is a question for the teacher, and guessing between
them could score a child wrongly").

`detect_item` reaches `MULTIPLE` only when `second >= FILL_MARKED and margin < MARGIN_CONFIDENT`
(`detector.py:366`). A runner-up that is unmistakably marked but *smaller in area* clears the
0.20 margin, falls through to the confident branch, and there both `strength` and `separation`
saturate to 1.0 (`detector.py:382-385`). Reproduced by sweeping the second mark's radius, both
marks at full darkness:
```
 r2   | fills[0] fills[1] | detected | outcome    | confidence
 0.50 |  0.8896   0.3977  | 0        | detected   | 1.0000  <-- silent single answer
 0.60 |  0.8896   0.5533  | 0        | detected   | 1.0000  <-- silent single answer
 0.65 |  0.8896   0.6637  | 0        | detected   | 1.0000  <-- silent single answer
 0.70 |  0.8896   0.7691  | None     | multiple   | 0.1989
 0.75 |  0.8896   0.8896  | None     | multiple   | 0.5000
```
A fill of **0.6637 is 1.9× `FILL_MARKED` (0.35)** — by the detector's own definition that bubble is
marked — and 74 % as filled as the winner. A student who fills B and puts a smaller mark in C gets
a single confident answer and never reaches the teacher.

Note the detector is blind to *darkness* differences (`_fill_ratio` thresholds at 0.82 × local
paper, so it is a step function: 0.0000 below pencil ~0.18, 0.8896 above). Area is the only channel
it can see, and area is exactly what this branch mishandles. Note also that `MULTIPLE`'s confidence
means the opposite thing on the same 0–1 scale — it *peaks* at 0.5 when the two fills are equal —
so the review queue's "lowest confidence first" ordering is non-monotonic across outcomes.

*Fix direction:* make the `MULTIPLE` test "is there a second bubble above `FILL_MARKED` at all",
independent of the margin; and put ungradeable outcomes on their own ordering key.

#### P1-10 · `process_page` computes a registration quality and never gates on it
`register` computes `quality` from side balance and aspect (`detector.py:222-233`), `process_page`
returns it, and `_persist_page` stores it in `registration_meta` — nothing ever tests it. A page
registered against the wrong four marks is therefore indistinguishable from a good one:
```
 0 fiducials erased -> registered=True  quality=1.0000  uid=7B_15  wrong items=0
 1 fiducials erased -> registered=True  quality=0.2780  uid=None   wrong items=1  max conf 0.4916
 2 fiducials erased -> registered=True  quality=0.1136  uid=None   wrong items=2  max conf 0.3743
 4 fiducials erased -> registered=True  quality=0.2856  uid=None   wrong items=9  max conf 1.0000
```
With all four corner marks gone the detector registered against four cells of the UID grid and
emitted nine wrong answers at confidence up to 1.0000. Only the UID checksum failing kept those
pages out of the record — and the documented recovery for an unidentified page is for the teacher
to assign it by hand, which would grade all nine.

`quality` below ~0.3 is a clean rejection signal that is already computed and already persisted.
*Fix direction:* refuse registration below a quality floor, and surface `quality` in the review UI.

#### P1-11 · Ungradeable detections vanish at confirm with no warning
`confirm_scan` blocks on unassigned *pages* only; every detection the grader cannot grade is
skipped silently (`scan_service.py:254-255`, `if not graded.gradeable: continue`). A double-marked
item therefore produces no `Attempt` and no notice — it simply is not in the record. Observed
directly: the same pile confirmed twice produced **24 then 23** attempts, the missing one being an
item that stayed `MULTIPLE`. `ScanConfirmResponse` reports `attempts_created`,
`students_affected` and `competencies_updated`, and no count of what was dropped.

The design intent is right (`scan_service.py:11-13`: "a zero is a claim about the student and
'unreadable' is not") — but not telling the teacher which items were dropped means an item can be
lost between the paper and the matrix with nothing anywhere saying so.

#### P1-12 · A corrupt upload reports the job as succeeded
```
GET /scans/901a380f-…  -> status "failed"
                          error  "could not read the upload: Failed to open stream"
GET /jobs/8b749d96-…   -> status "succeeded", progress 1.0, error null,
                          message "queued for registration and detection"
                          result {"error":"could not read the upload: …","pages":0,"registered":0}
```
`process_scan` catches the decode failure, sets `scan.status = FAILED` and *returns a dict*
(`scan_processing.py:195-200`), so the job wrapper records success. A client that polls the job —
which is exactly what the upload flow is meant to do — sees green and then an empty review screen.
The raw PyMuPDF string is also passed straight to the teacher, untranslatable and unactionable.

#### P1-13 · `scan_processing.py` is executed by no test at all
The module bridging detector output to database rows is at **0 % coverage** and is never imported
by the suite (`grep -rn "scan_processing\|process_scan" apps/api/tests` matches only the string
`"/api/v1/jobs?kind=process_scan"` in a query parameter). P0-2, P0-3, P0-4, P1-5 and P1-11 all live
there. The API tests hand-construct `Detection` rows (`test_api_scans.py:104-213`), so no test
anywhere runs the detector and the persistence layer together — which is precisely the seam that
is broken.
### P2

#### P2-1 · The review rows show a bare number — no statement, no options, no answer key
Each row renders `#{detection.item_index + 1}` (`page.tsx:136-138`), an outcome badge, a
`ConfidenceBar` and a segmented control. There is no question text, no printed item number, no
correct answer. A teacher asked to adjudicate "#7, low confidence, A/B/C/D" has nothing to
adjudicate against — they would have to fetch the paper copy. `scan_processing.py:142-143` states
the intent ("so the review UI can show the statement next to the mark it read") and the
`sheet_item_id` needed for it is on the wire (`DetectionOut.sheet_item_id`), but the screen never
resolves it. Note also `item_index` is page-local, so on page 2 the rows restart at "#1" while the
paper says "17."

#### P2-2 · True/false items are labelled A/B instead of Vrai/Faux
`page.tsx:172-175` labels the override control with `'ABCD'[i]`, driven only by
`detection.fill_ratios?.length ?? 4`. A true/false item shows "A / B" where the paper shows
"V / F" (or R/F, T/F — `layout.tf_letters`). The teacher has to know that bubble 0 means true. The
sheet's language is available on the sheet; the layout module already owns the glyph mapping.

#### P2-3 · Rotation tolerance is ~7°, and it depends on how the page is framed
The detector registers reliably to ±7°; beyond that the result depends on how much blank margin
surrounds the page, which is not a property anything controls:
```
 angle | pad=0.20            | pad=0.35            | pad=0.60
    7° | reg=True  16/16     | reg=True  16/16     | reg=True  16/16
   10° | reg=True  16/16     | FAIL found 2 fiduc. | FAIL found 2 fiduc.
   15° | reg=True  16/16     | FAIL found 0 fiduc. | FAIL found 0 fiduc.
   17° | FAIL found 0 fiduc. | FAIL found 0 fiduc. | FAIL found 0 fiduc.
```
Cause: `find_fiducials` derives its area gate from `min(h, w)` of the **whole image**
(`detector.py:135-137`), so more surrounding whitespace changes which contours survive; and the
`extent >= 0.72` gate (`:158-159`) uses an *axis-aligned* bounding box, so extent falls as
`1/(cosθ+sinθ)²` and the fiducial's outer contour is already rejected at 10° (0.717). Registration
survives past that only because `_binarise` turns each solid square into a ring whose smaller inner
contour keeps a higher extent — an unintended by-product of the adaptive-threshold block size, not
a designed margin. The existing tests cover +2° and −5° only.

It fails safely (registration error, page goes to manual) — but per P1-2 and P1-7 there is no
manual path, so in practice a crooked copier feed deadlocks the batch. Related near-miss: at a ~20°
tilt `find_fiducials` returned two real fiducials plus **two UID-grid cells** as corners; the page
was saved only by `register`'s degeneracy guard, not by anything checking that the quadrilateral
looked like a page.

#### P2-4 · Verified on synthetic and generated-PDF data only
`docs/samples/scans/` does not exist (`ls: docs/samples/: No such file or directory`) and there is
no photograph of a real printed sheet anywhere in the repo. This is weaker than it sounds — I did
verify `layout.py` against the **real generated PDF** to 0.14 mm and ran the full loop on it — but
no ink has ever touched paper: the printer's own scaling, a photocopier's transfer curve, a camera
lens and real pencil are all still untested. `docs/handover.md:15` records the milestone as
"verified against synthetic degradation only", which remains the right description.

#### P2-5 · The demo seed cannot detect a grading bug
Every MCQ in the seed has `answer_index = 0`, so a pipeline that always guessed "A" would score
100 % against the demo data. Any accuracy figure computed from the seed alone is meaningless; my
numbers come from marks planted per student. Worth varying in the seed.

#### P2-6 · HEIC is not accepted, though R1 asks for "HEIC-if-claimed"
`core/config.py:71-76` — `allowed_upload_types = ("application/pdf", "image/jpeg", "image/png",
"image/webp")`. Tested with **real HEIC bytes** (macOS `sips -s format heic`, magic `ftypheic`) and
with JPEG bytes relabelled `image/heic`; both 415 at the declared-type gate before any sniff:
`"content type 'image/heic' is not accepted"`. Given `docs/plan.md` §9 makes phone capture an
explicit workflow and iOS defaults to HEIC, this needs a decision rather than an omission — accept
and transcode, or record why not in the decisions log.

#### P2-7 · Phone touch targets on the override control are below 44 px
At 390 px the segmented override options measure **34×36, 33×36, 33×36, 33×36, 33×36 px**, against
the ≥44 px floor in `DESIGN.md` §6 and `docs/plan.md` §9 — which calls out this control by name:
"Detection-correction controls in the scan review get 44 px hit areas even when visually smaller."
The `.ard-btn` Confirm button is correct at 44 px.

#### P2-8 · Raw library and validation strings reach the teacher
A corrupt PDF surfaces `"could not read the upload: Failed to open stream"` — the PyMuPDF
exception, passed through by `scan_processing.py` — and a failed upload renders the API's
`"request body failed validation"` verbatim on the upload screen. Neither is translatable and
neither tells a teacher what to do. (F1-review raised the same class of issue; `7757659` fixed it
for sheet previews only.)

#### P2-9 · The low-confidence threshold is duplicated as a TypeScript literal
`detector.py:53` `LOW_CONFIDENCE = 0.65` and `page.tsx:19` `const LOW_CONFIDENCE = 0.65` are
independent constants. `ConfidenceBar` and `ScanReviewOverlay` both default their threshold to
`0.8` (`ConfidenceBar.tsx:31`, `ScanReviewOverlay.tsx:82`), a third value. The repo already exports
layout constants to TypeScript (`packages/shared/src/layout.generated.ts`, via
`scripts/export-layout.py`); the detection thresholds should ride the same path.

#### P2-10 · The per-bubble `LOW_CONFIDENCE` branch is never executed by a test
`detector.py:374-378` (faint-but-present mark) and `:389` (confident branch falling through to
low confidence) are the band the safety design is built around, and no test reaches them: the
pencil 0.45–0.9 cases land in the confident branch and the pencil 0.22 case lands in `BLANK` and is
rescued by the page-level `_flag_suspicious_blanks`. Three of the four `RegistrationError` paths
(`:179`, `:186`, `:228`) and the detector's handling of an undecodable printed UID (`:316`,
`:319-320`) are likewise untested.

#### P2-11 · Two API tests assert a status code and nothing else
`test_api_scans.py:40` (`test_upload_accepts_a_phone_photo`) asserts only
`response.status_code == 202` — no body, no row, no job. `:78`
(`test_upload_rejects_an_empty_file`) asserts only `422`, unlike its four sibling validation tests
which check `error.code`.

### P3

#### P3-1 · The grader registry is private with no registration function
R8 asks for "a grader interface where a free-text grader could be registered". `ItemGrader` is a
`Protocol` (`grading.py:47`) and dispatch is table-driven (`:118-130`), which is the right shape,
but `_GRADERS` is module-private and `alppy/scan/__init__.py` exports nothing. Registering means
reaching into a private name. A `register_grader(type, grader)` function would make the seam real.
The behaviour R8 actually requires is correct: `open` returns `NOT_GRADEABLE` and is never scored
(`grading.py:109-115`, `test_grading.py:55`).

#### P3-2 · A true/false correction accepts option indices 2 and 3
`DetectionCorrection.detected_index` is bounded `ge=0, le=3` (`schemas/__init__.py:284`) with no
reference to the item's option count, so a teacher (or a client bug) can set a two-option item to
option 3. `_grade_true_false` then compares it against 0/1 and scores the child wrong.

#### P3-3 · `detected_bool` is populated for MCQ rows, where it means nothing
`_persist_page` sets `detected_bool = (detected_index == 0)` for every detection regardless of
exercise type (`scan_processing.py:163-168`), so an MCQ answered "C" carries `detected_bool=False`.
`correct_detection` gets this right (it checks the exercise type); the detection writer does not.

#### P3-4 · There is no keyboard path to the next low-confidence item
The whole point of the review screen is that attention goes where the machine is least sure, and
the tab order offers no way to act on that: 9 stops of chrome, then Confirm, then one stop per
item group. With 28 pages × 16 items that is hundreds of Tab presses, and Confirm sits *before*
every item, so correcting the last one means Shift-Tabbing back through all of them. Override and
Confirm are both operable by keyboard, and focus rings are visible throughout.

#### P3-5 · `Scan.error` is cleared on confirm
`scan_service.py:275` sets `scan.error = None` when confirming, discarding whatever the processing
stage recorded. Minor, but it removes the record of a partially-failed batch.

### What holds up — and it is the hard part

The detector is not the problem, and that matters for how this report should be read.

- **0 wrong UIDs, anywhere.** 630 `process_page` calls over 45 pages × 14 conditions, plus 864
  stress pages, plus every adversarial probe: not one page ever decoded to a *different real
  student*. Reads either resolve exactly or fail. D2's central safety claim is earned.
- **0 wrong items under degradation.** 8 640 / 8 640 correct on registered pages. Registration
  survives ±5° rotation, perspective to `s=0.220` (~14°), JPEG q40, 150 dpi, a 0.35 shadow
  gradient, and the composite `phone_photo()` and `copier()` presets at 100 %. In 22 464 degraded
  items the detector never once picked a *different option* because of image quality — its failure
  mode is always "lost the mark, flag it".
- **`layout.py` and the printed PDF agree.** Bubble centres extracted from the real generated
  `blank.pdf` drawing operators vs `L.bubble_centre_mm()`: **max deviation 0.14 mm** on a 5 mm
  bubble.
- **The real end-to-end path is exact.** The F1-generated blank PDF for 7B, filled programmatically
  and pushed through upload → worker → detections → confirm: **24/24 items and 12/12 UIDs correct**
  on 6 students, then **100/100 attempts matching ground truth** on 25. Re-run through
  `phone_photo` and `copier`: still 24/24 and 6/6.
- **Confidence does separate correct from incorrect — for mark-quality errors.** The main sweep
  produced no errors at all, so AUC was undefined there; on a purpose-built stress population
  (13 824 items, pencil 0.16→0.70, mark jitter) **AUC = 0.9760**, and **3 357/3 357 (100 %) of
  incorrect items fall below the 0.65 threshold** — the review queue surfaces every error it makes,
  at a cost of 8.7 % false alarms (~1.4 per page). The prioritisation R6 depends on is sound.
  The critical caveat is P1-9 and P1-10 above: confidence is **blind to geometry errors**.
- **Speed is a non-issue.** Detector CPU 21 ms/page (my own runs: 28 ms clean, 16 ms `phone_photo`);
  end-to-end through the worker **0.096 s/page** — a 28-page batch in 2.68 s.
- **`grading.py` is clean**, and the `open` seam is honoured exactly as CLAUDE.md and D13 require:
  30 detections → 24 attempts, the free-text item scored by nothing.
- **Design and i18n pass.** No colour literal outside `tokens.css`/`print.css`; no mandarin accent
  anywhere on the F2 screens; no Caveat; `.ard-btn` carries a solid `--edge` and a Fredoka label;
  Card and Panel used per the rule (1 card, 17 panels). All seven theme/contrast/motion/calm states
  legible — dark body text 16.51:1, high contrast 21:1 — with no light box left on the dark canvas.
  No horizontal body scroll at 390 px or 1440 px. `pnpm i18n:check`: 261 keys in sync; every visible
  string changes across fr/de/en.
- **Privacy is not at risk in this phase.** The scan path imports nothing from `alppy.ai`, makes no
  network call, and no student name appears in any scan schema; `model_call` was empty after every
  run. R9 is satisfied because the vision fallback it guards against does not exist.
- **`ruff`, `mypy --strict` and 300 tests pass clean**, no skips, no xfails. The detector's own
  degradation suite (`test_scan_pipeline.py:51-71`) is genuine and covers all seven axes.

## 5. Not checked

I worked this list out before writing the verdict, not after.

- **Real paper — the largest gap.** No printed sheet was scanned, photographed or photocopied;
  `docs/samples/scans/` does not exist and this machine has no scanner. Two links of the chain *are*
  now closed: `layout.py` matches the real generated PDF to 0.14 mm, and the full loop is exact on
  that PDF. What has never happened is ink on paper — the printer's own scaling, a photocopier's
  transfer curve, a phone lens, and a real pencil. Every accuracy figure above should be read as
  "the geometry and the logic are right", not as "this works in a classroom". That is the one thing
  I would do before trusting these numbers with a real class.
- **The confidence-separation figure rests on a population I designed.** The required sweep produced
  no errors, so AUC was undefined; the 0.9760 comes from a stress population I built to have errors
  in it, with mark jitter and pencil strengths I chose. It is evidence that the mechanism works, not
  a measurement of a real error rate.
- **HEIC with genuine HEIC bytes.** The format is rejected at the content-type gate before any
  decode, so I did not construct a real HEIC file; I verified the allowlist and the rejection path
  only.
- **200 students / a 200-page upload.** `MAX_PAGES = 200` (`scan_processing.py:41`) is enforced only
  for PDFs and silently truncates rather than warning; I did not test at that size, so I cannot say
  how the worker behaves on memory or how long a real 200-page batch takes. At the measured 21 ms
  per page the detector is not the constraint, but PDF rasterisation at 200 dpi and the per-page
  PNG writes were not profiled.
- **A rotated phone photo of a real page.** I established the rotation limit synthetically
  (~7° dependable, see P2-3) but not with a real camera, real lens distortion or motion blur. The
  finding that tolerance *depends on the surrounding margin* also means my numbers are specific to
  a full-bleed A4 render; a real photo with desk visible around the page may behave differently in
  either direction.
- **Concurrency.** Two teachers confirming the same scan at once, or a confirm racing the worker.
  `confirm_scan` guards on status but there is no row lock; I did not probe it.
- **The mastery consequences of the mis-grading defects.** I verified that P0-3 and P0-4 write wrong
  `Attempt` rows, and that `recompute_for_students` is called, but I did not trace how far a wrong
  band propagates into F3's matrix or F5's adaptive targeting.
- **`data-calm` and `data-motion` in any meaningful sense.** The F2 screens carry no decorative
  illustration and no animation, so both states pass trivially. I screenshotted them; that is not
  the same as testing them.
- **Whether the P0 fixes interact.** P0-2 (no `sheet_id`) currently masks P0-3 and P0-4 on the UI
  path, because unpaired detections are dropped before they can be mis-paired. Fixing P0-2 alone
  would turn "nothing is graded" into "some things are graded wrongly", which is worse. I did not
  verify any fix ordering; the fix brief says to land them together.
- **Whether `_flag_suspicious_blanks`' 60 % threshold is right.** I confirmed it fires and that it
  is what rescues the off-centre and faint-mark cases. Whether 60 % is the correct number for a real
  class is a calibration question that needs real sheets.

## 6. Reviewer changes

- Created `docs/reviews/screenshots/F2/` and wrote screenshots into it.
- Wrote this report.
- **No file under `apps/`, `packages/` or `infra/` was modified.** No fix was applied: nothing
  blocked verification in a way that a five-line change would have unblocked — the API path was
  usable throughout by sending the correct multipart field name, which is what I did to exercise
  everything downstream of P0-1.
- Reproduction scripts live in the session scratchpad, not in the repo:
  `test_repro_{nosheet,itemplan,multipage,wrongclass,idempotency}.py`. They are written against
  `apps/api/tests/test_api_fixtures.py` and are ready to move into `apps/api/tests/` as regression
  tests; the fix brief asks for exactly that.

---

## 7. Fix brief

> Copy everything below into a fresh session.

---

You are fixing phase **F2 (scan and correction)** of Alppy. Read `CLAUDE.md` and `DESIGN.md` first.

The detector (`apps/api/alppy/scan/detector.py`) is **very good and well tested** — it read
8 640/8 640 items and 0 wrong UIDs across 630 degradation runs. **Do not retune `FILL_MARKED`,
`FILL_BLANK`, `LOW_CONFIDENCE`, `_fill_ratio` or any geometry**; the only two changes it needs are
items 9 and 10 below, and both are added guards, not retuning. Everything else is in the layer
between the detector and the database, or in the web client.
`apps/api/alppy/services/scan_processing.py` currently has **0 % test coverage and is imported by
no test**; that is why all of this survived to this review.

**Add a regression test for every item below.** Put pipeline tests next to
`apps/api/tests/test_scan_pipeline.py` and integration tests next to
`apps/api/tests/test_api_scans.py`; they must drive the real `scan_processing.process_scan` and
`scan_service.confirm_scan`, not hand-built `Detection` rows. `apps/api/tests/test_api_fixtures.py`
gives you `db`, `storage`, `tenant`, `client`; `alppy.scan.synthetic.render_page` gives you a page
the detector can read.

**Land the four P0s together, in this order.** P0-2 currently *masks* P0-3 and P0-4: with no
`sheet_id`, detections are unpaired and dropped before they can be mis-paired. Fixing P0-1 and P0-2
first, alone, converts "nothing is graded" into "some children are graded wrongly", which is worse
than today. Fix P0-3 and P0-4 in the same change.

### P0-1 · The UI cannot upload at all
`apps/web/src/lib/api/endpoints.ts:135-140` sends `formData.append('files', file)`;
`apps/api/alppy/api/v1/scans.py:57` requires `file`. Every browser upload is a 422.
```
curl -b jar -X POST localhost:8000/api/v1/scans -F "files=@p.png;type=image/png"   # 422
curl -b jar -X POST localhost:8000/api/v1/scans -F "file=@p.png;type=image/png"    # 202
```
The endpoint takes one file per scan while the picker is `multiple`; decide which (one scan per
file, or a real multi-file endpoint) and make both sides agree.
**Accept:** dropping a PDF and dropping three photos on `/fr/scans/new` both start processing, in a
browser. **Regress:** an e2e test that uploads through the real API, not the fixture layer — the
gap `docs/handover.md:107-110` already names, and the same bug F1-review P0-3 found in `/sources`.

### P0-2 · Confirming writes zero attempts and reports success
The upload screen never sends `sheet_id` (`scans/new/page.tsx:19`, no sheet picker), so every
`Detection` gets `sheet_item_id = NULL` and `confirm_scan` skips all of them
(`scan_service.py:249-252`), returning `attempts_created=0` while flipping the scan to `confirmed`
and rendering "Résultats enregistrés".
**Accept:** a scan uploaded through the UI produces attempts; a confirm that would produce none
fails loudly instead of reporting success. **Regress:** `test_repro_nosheet.py` (in the scratchpad),
asserting `attempts_created > 0` on the UI path.

### P0-3 · A differentiated copy is graded against the wrong exercises
`scan_processing.py:151-155` pairs a detection to `sheet_items[placed_item.number - 1]` — the
sheet's list indexed by the copy's number. `create_adaptive_sheet` (`sheet_service.py:186-189`)
makes `sheet.items` the union over the class while each instance's `item_plan` is that student's
subset, so the mapping is wrong for every adaptive sheet. Reproduced: a student who answered both
their items correctly scored 0/2, at `outcome=detected`, one attempt filed against an exercise that
was never on their copy.
Resolve through the copy's own `item_plan` (you already have the `SheetInstance` for that UID), and
persist the resolved `exercise_id` on the `Detection` so the pairing is auditable.
**Accept:** `test_repro_itemplan.py` passes — pairing `{0: E3, 1: E1}`, both attempts correct.

### P0-4 · One unreadable page shifts every copy behind it
`_page_within_copy` (`scan_processing.py:263-272`) uses `scan_page_index % len(pages)` — the global
index in the upload — although the UID is already decoded for that page. A 5-item MCQ sheet
paginates to three physical pages, so this is the normal case. With one unreadable page at the
front of a 6-page pile, **8 of 10 attempts were graded wrong** for students who answered everything
correctly.
Count pages per decoded UID; a page whose UID did not decode belongs to no copy and must not
consume a slot.
**Accept:** `test_repro_multipage.py` passes — 0 wrong with and without junk pages in the pile.

### P1 — fix in the same pass

1. **The review screen never shows the scanned page.** `ScanReviewOverlay` is built, exported and
   imported by nothing. Two prerequisites: `scan_processing.py:227` stores the raw upload — store
   `reg.canonical` (the deskewed page) instead; and the detector's `u,v` are fiducial-frame
   normalised (18–192 mm of a 210 mm page) while the overlay treats them as image-box fractions —
   measured 8–17 mm out on a *flat* page, 1–2 bubble pitches. Fix one frame or the other, then wire
   the overlay. **Accept:** boxes sit on the bubbles on a deliberately skewed scan.
2. **No manual student-assignment UI.** `useAssignScanPage`, `PATCH /scans/{id}/pages/{id}` and the
   strings `scans.assignManually` / `scans.chooseStudent` all exist and are dead. Also: the client
   calls `POST …/pages/{id}/assign`, which is not a route; and `assign_page_student`
   (`scan_service.py:303-305`) scopes candidates to the school, not to the sheet's class as R3
   requires. **Accept:** a page with an unreadable UID offers a picker listing only that class.
3. **A correction destroys the machine's reading.** `correct_detection` (`scan_service.py:169-180`)
   overwrites `detected_index`, `outcome` and `confidence` in place; `Detection` has no column for
   the original, though the docstring at `:9-10` claims it is kept. Add immutable
   `machine_index` / `machine_outcome` / `machine_confidence` (migration) and show both in the UI.
4. **`layout_version` is loaded and never read.** `scan_processing.py:202-206` has the sheet;
   `process_page` has no version parameter. Thread it through and refuse (or route to manual) a
   version the detector does not implement, so `layout.py:12` becomes true before v2 exists.
5. **Foreign-class pages are not flagged.** `_resolve_student` (`scan_processing.py:91-98`) matches
   on school + UID only. Flag a page whose student is not in the sheet's class; add the column and
   surface it. **Accept:** a 28-page batch with 2 foreign pages and 1 blank reports 25 assigned,
   2 wrong-class, 1 unreadable.
6. **No progress and no polling.** The worker reports per-page progress (`scan_processing.py:242`)
   and nothing reads it. Neither scan screen uses `useJob`; `useScan` has no `refetchInterval`, so a
   processing scan renders as a finished empty one with Confirm enabled.
7. **An unassignable page deadlocks the scan.** `confirm_scan` refuses while any page lacks a
   student (`scan_service.py:225-230`) and no route can discard a page. Add a discard/ignore action.
8. **Re-uploading duplicates attempts.** No unique constraint on `attempt`
   (`models/__init__.py:486-488`); the same pile confirmed twice doubled 2 of 2 (student, exercise)
   pairs. Add the constraint and an upsert-or-supersede rule.
   **Regress:** `test_repro_idempotency.py`.
9. **A partially-filled second bubble is silently accepted (P1-9) — the one detector defect.**
   `detect_item` reaches `MULTIPLE` only when `second >= FILL_MARKED and margin <
   MARGIN_CONFIDENT` (`detector.py:366`); a runner-up at fill 0.6637 — 1.9× `FILL_MARKED` — clears
   the margin and the item is reported `detected` at **confidence 1.0000**. Violates R4 and D5.
   Make the `MULTIPLE` test "is any second bubble above `FILL_MARKED`", independent of the margin.
   Also give ungradeable outcomes their own ordering key: `MULTIPLE`'s confidence *peaks* at 0.5
   when the fills are equal, so the review queue's sort is non-monotonic across outcomes.
   **Accept:** a full mark plus a 0.45–0.68-radius mark on the same item yields `MULTIPLE`.
10. **`process_page` never gates on registration `quality` (P1-10).** It is computed
   (`detector.py:222-233`), returned, and stored in `registration_meta`, and nothing reads it. With
   all four fiducials erased the page still "registers" at quality 0.2856 and emits 9 wrong items at
   confidence 1.0000 — only the UID checksum failing kept them out of the record, and the documented
   recovery for an unidentified page is manual assignment, which would have graded all nine. Add a
   quality floor and surface the value in the review UI.
11. **Ungradeable detections vanish at confirm (P1-11).** `scan_service.py:254-255` skips them
   silently; a double-marked item produces no `Attempt` and no notice. Return a count of dropped
   items in `ScanConfirmResponse` and show it.
12. **A corrupt upload reports the job as succeeded (P1-12).** `process_scan` catches the decode
   failure, sets `scan.status = FAILED` and *returns a dict* (`scan_processing.py:195-200`), so the
   job wrapper records `succeeded` at progress 1.0 with `error: null`. Raise, or mark the job failed.
   The raw PyMuPDF string also reaches the teacher.
13. **`scan_processing.py` has no tests.** Fixing 1–12 without covering this module leaves the same
   hole open. Every P0 above must land with a test that runs the real pipeline.

### P2 — worth doing, not blocking

Review rows show a bare `#n` with no statement, options or key, and page-local numbering restarts
at #1 on page 2 · true/false options labelled A/B instead of V/F · rotation tolerance is ~7° and
*depends on how much blank margin surrounds the page*, because `find_fiducials` derives its area
gate from the whole image and its extent gate from an axis-aligned box · every MCQ in the demo seed
has `answer_index = 0`, so the seed cannot detect a grading bug · HEIC rejected though phone capture
is an explicit workflow · phone override targets 33-34×36 px against the 44 px floor · no keyboard
path to the next low-confidence item, and Confirm precedes all 16 item groups in the tab order ·
`LOW_CONFIDENCE` duplicated as a TS literal (0.65) while both UI components default to 0.8 — export
it like `layout.generated.ts` · `detector.py:374-378` and `:389` (the faint-mark band) executed by
no test · two API tests assert only a status code (`test_api_scans.py:40`, `:78`) ·
`detected_bool` populated meaninglessly for MCQ rows · no real scanned sample anywhere in the repo.

### Do not "fix"

`_fill_ratio`'s local-annulus threshold, `_flag_suspicious_blanks` and its 60 % ratio, the CRC-8
UID grid, `grading.py`'s `NOT_GRADEABLE` seam, and the synthetic degradation suite. These are the
parts that work, and several of them are the only reason the failures above are recoverable rather
than silent. Items 9 and 10 add guards *around* the detector's decisions; they do not retune them.
