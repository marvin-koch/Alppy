# Scanning

**Status:** describes `main` as of 2026-09-09
**Audience:** developers, LLM agents, reviewers
**Layout version read:** v1 (a page stamped with another version is refused)

---

## 1 · What it does

A teacher photographs a pile of completed copies with a phone, or scans them to a
PDF, and drops the lot on `/scans/new`. This subsystem turns those pixels into
reviewable `Detection` rows: one per printed item, carrying what the machine read
and how sure it is.

It reads **geometry, never words**. Four corner fiducials give a perspective
transform onto a canonical page; the UID grid gives the student; the bubble
coordinates come from `alppy.sheets.layout`. Nothing on the page has to be legible
as text for any of it to work — which is exactly why it survives a photocopy of a
photocopy taken at an angle in bad light.

It also **grades nothing**. Grading happens on confirm, after a human has looked at
the low-confidence items (see [`../grading/`](../grading/)).

```
  upload (jpg | png | heic | pdf)  ──▶  Scan + Job(PROCESS_SCAN)     [request returns]
                                             │
                                             ▼  arq worker
                              _decode_pages ──▶ one image per page
                                             │
                              detector.register()   4 fiducials → perspective transform
                                             │      → canonical page at 8 px/mm
                                             ├──▶ read_uid_grid()   32 bits, CRC-8
                                             │        │ fails → page waits for the teacher
                                             ├──▶ detect_item(i)    fill ratio + cross score
                                             │        │              → DETECTED | LOW_CONFIDENCE
                                             │        │                | BLANK | MULTIPLE
                                             └──▶ crop_answer_box()  at AnswerBoxPlacement
                                                      │              → PENDING (or BLANK)
                                                      ▼
                                             Detection[] ──▶ review UI
                                                      │
                                             Job(GRADE_OPEN_ANSWERS) chained
```

### Key properties

1. **A page belongs to a copy because of what is printed on it**, never because of
   where it sat in the upload.
2. **The machine's reading is written once.** `machine_index`, `machine_outcome`,
   `machine_confidence` are set at detection time and never updated; a teacher's
   correction goes beside them, not over them.
3. **Uncertainty is a first-class outcome.** `LOW_CONFIDENCE`, `MULTIPLE`, `PENDING`
   and `NOT_GRADEABLE` all exist so that "I could not read this" never has to be
   expressed as a zero.

---

## 2 · Invariants (load-bearing)

| # | Invariant | Enforced in | Why it matters | Failure symptom |
|---|---|---|---|---|
| I-scanning-01 | Registration is by **four fiducials only**; failure raises `RegistrationError` rather than falling back to a guess. | `scan/detector.py::find_fiducials`, `::register` | A mis-registered page reads every bubble at the wrong place | A whole copy graded against neighbouring bubbles |
| I-scanning-02 | The UID is read from a **32-bit CRC-8 grid**. A failed checksum is a *failure*, sent to the teacher — never a decode to a different real student. | `sheets/uid_code.py::decode_uid`, `detector.read_uid_grid` | A wrong decode files a child's answers under someone else's name | Silent misattribution, undetectable afterwards |
| I-scanning-03 | **Which page belongs to whose copy is resolved from the decoded UID**, never from the position in the upload. | `services/scan_processing.py::_copies_by_uid`, `_resolve_student` | One unreadable photo used to shift every copy behind it | A whole class graded against the wrong questions |
| I-scanning-04 | Bubble fill is measured against a **local annulus**, not a global threshold; a cross is read by shape as well as by ink. | `scan/detector.py::_sample_ink`, `_fill_ratio`, `_cross_score`, `_mark_strength` | Grey photocopy paper and light pencil both defeat a global threshold | A light pencil mark scored as blank, i.e. a silent zero |
| I-scanning-05 | A page that reads **mostly blank distrusts its own blanks**: above 60 % blank, every blank is downgraded to `LOW_CONFIDENCE`. | `scan/detector.py::_flag_suspicious_blanks` | A page whose pencil the copier lost looks identical to an empty one, per bubble | A copy silently scored zero throughout |
| I-scanning-06 | The **machine's reading is written once**. A correction is `CORRECTED`, with who and when, beside `machine_*`. | `services/scan_service.py::correct_detection` | "The teacher disagreed with the scanner" is the fact worth auditing | The detector's accuracy becomes unmeasurable |
| I-scanning-07 | A crop is cut at the **measured `AnswerBoxPlacement`**, in the canonical frame, and **never leaves the statement region**. | `services/scan_processing.py::_placements_by_uid`, `_crop_answer_boxes`; `scan/answer_box.py::crop_answer_box` | Only geometry keeps a student code out of an image sent to a provider | PII leak, or a crop of the wrong item |
| I-scanning-08 | An item belongs to **the paper it was printed on**: the exercise is resolved through that copy's own pagination and stored on the row. | `services/scan_processing.py::_persist_detections`, `_sheet_items_by_exercise` | A differentiated copy prints its own item list | A differentiated copy graded against the class list |
| I-scanning-09 | A page printed under **another `layout_version` is refused**, not read. | `services/scan_processing.py::process_scan` | Old coordinates ≠ new coordinates | Last term's pile graded against this term's geometry |
| I-scanning-10 | The **stored page image is the registered one**, and re-detection re-reads it. | `services/scan_processing.py::_store_page_image`, `redetect_page` | The teacher's review overlay must line up with what was measured | Overlay boxes drawn where nothing is |
| I-scanning-11 | **Reverting a correction restores the machine's own reading** from `machine_*` and invents nothing. Refused on a reading that was never corrected. | `services/scan_service.py::revert_detection` | The write-once audit columns exist precisely so an override can be undone | An "undo" that writes a fresh guess and calls it the machine's |
| I-scanning-13 | **A job's `message` never reaches the teacher.** The waiting state is built from `status` and `progress`; the server string is a log line and is English by construction. | `scans/[scanId]/page.tsx`, D55 | Three catalogues cannot translate a string invented in the worker | A French teacher reads "queued for registration and detection" |
| I-scanning-12 | The per-item confidence report is keyed by **question, never by `item_index`**, which is page-local and restarts at 0 on every page (I-sheets-06). | `services/scan_service.py::confidence_by_item` | Page two's first item otherwise collides with page one's | A question silently missing from the report |

---

## 3 · Module map

| Path | Owns | Depends on |
|---|---|---|
| `alppy/scan/detector.py` | Fiducials, perspective registration, the canonical 8 px/mm frame, ink sampling, fill + cross scoring, UID read, `process_page()` | `sheets.layout`, `sheets.uid_code`, OpenCV, NumPy |
| `alppy/scan/answer_box.py` | `crop_answer_box()`, painting out Alppy's own printed furniture, "is there any ink at all", `encode_png()` | `detector.PX_PER_MM`, `sheets.layout` |
| `alppy/scan/synthetic.py` | The synthetic degradation suite: printed pages, pencil, crosses, blur, skew, copier loss | `sheets.html`, `layout` |
| `alppy/services/scan_processing.py` | Decoding an upload (incl. HEIC), page → copy resolution, persisting detections and crops, `redetect_page`, manual assignment | `scan/*`, `models`, `storage` |
| `alppy/services/scan_service.py` | Upload, listing, teacher correction, page assignment, discard, confirmation | `scan_processing`, `scan.grading`, `models` |
| `alppy/api/v1/scans.py` | Endpoints, upload validation (type sniffing, size cap, filename safety) | `scan_service`, `deps` |
| `apps/web/src/app/[locale]/scans/` | Upload with `capture="environment"`, review overlay with confidence bars | `packages/shared` |

---

## 4 · How to extend this feature

1. **Read §2.**
2. Changing a **threshold** (`FILL_MARKED`, `FILL_BLANK`, `MARGIN_CONFIDENT`,
   `LOW_CONFIDENCE`, `MOSTLY_BLANK_RATIO`) is a change to how often a child is
   silently scored zero. Run the synthetic degradation suite before and after and
   report both numbers in the PR.
3. Changing a **coordinate** is not this feature's decision at all — it is
   `I-sheets-03`, a layout version bump.
4. New input formats go through `_decode_one`, which sniffs content rather than
   trusting the declared type.

### LLM checklist

- [ ] Read §2 — these are not suggestions
- [ ] Does the change let an unreadable mark become a score? (I-scanning-04/05)
- [ ] Does it write over `machine_*`? (I-scanning-06 — never)
- [ ] Does it resolve a page by upload order anywhere? (I-scanning-03 — never)
- [ ] Does it recompute a box instead of reading a placement? (I-scanning-07 — never)
- [ ] Did a threshold move? Then the synthetic suite is part of the diff

---

## 5 · Privacy & safety

| Data | Where it is stopped | Why |
|---|---|---|
| Student name | Never printed, so never in a page image or a crop | The crop is bytes to a vision model; nothing can scrub a photograph |
| Student UID | Above `ITEMS_TOP_MM`; a crop is refused if it reaches there | Geometry is the gate for images (`I-scanning-07`, `I-sheets-08`) |
| The page image itself | Object storage, tenant-scoped route | See [`../../privacy.md`](../../privacy.md) |
| Uploaded filename | `storage.sanitise_filename` — never becomes a path | `../../etc/passwd` is stored as `etc_passwd` |

**Never a silent zero.** This is the safety rule of the whole subsystem. Every
mechanism above — the local annulus, the cross score, the blank-page distrust, the
`LOW_CONFIDENCE` outcome — exists so that "the scanner could not read it" reaches the
teacher instead of reaching the child's record as a wrong answer.

---

## 6 · Testing strategy

| Invariant | Proved by |
|---|---|
| I-scanning-01 | `test_scan_pipeline.py::test_a_page_without_fiducials_fails_registration_cleanly`, `::test_a_crooked_page_still_registers`, `::test_decoy_squares_do_not_displace_a_real_fiducial` |
| I-scanning-02 | `test_uid_code.py::test_every_single_bit_error_is_rejected`, `::test_every_double_bit_error_is_rejected`, `test_scan_pipeline.py::test_uid_is_read_for_several_classes` |
| I-scanning-03 | `test_scan_processing.py::test_an_unreadable_page_does_not_shift_the_copies_behind_it`, `::test_a_page_from_another_class_is_flagged_and_not_graded` |
| I-scanning-04 | `test_scan_pipeline.py::test_light_pencil_still_reads_through_a_phone_photo`, `::test_a_fine_pen_cross_is_rescued_from_reading_blank`, `::test_a_stray_line_through_a_bubble_is_not_read_as_a_cross` |
| I-scanning-05 | `test_scan_pipeline.py::test_a_mark_lost_by_the_copier_is_flagged_not_silently_zeroed`, `::test_a_genuinely_empty_page_is_sent_for_review`, `::test_a_fine_pen_cross_is_never_silently_scored_zero` |
| I-scanning-06 | `test_scan_processing.py::test_a_correction_keeps_the_machine_reading_beside_it`, `test_api_scans.py::test_a_correction_records_who_and_when` |
| I-scanning-07 | `test_answer_box_crop.py` (whole file), `test_scan_processing.py::test_a_written_answer_is_cut_and_left_pending_for_the_grader` |
| I-scanning-08 | `test_scan_processing.py::test_a_differentiated_copy_is_graded_against_its_own_items` |
| I-scanning-09 | `test_scan_processing.py::test_a_page_printed_under_another_layout_is_not_read` |
| I-scanning-10 | `test_scan_processing.py::test_the_stored_page_image_is_the_registered_one` |
| I-scanning-11 | `test_scan_processing.py::test_reverting_a_correction_restores_the_machines_own_reading`, `::test_reverting_a_reading_that_was_never_corrected_is_a_conflict` |
| I-scanning-12 | `test_reports.py::test_an_item_on_the_second_page_does_not_hide_the_first_pages_item` |

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_scan_pipeline.py \
  apps/api/tests/test_scan_processing.py apps/api/tests/test_answer_box_crop.py \
  apps/api/tests/test_uid_code.py apps/api/tests/test_print_scan_roundtrip.py -q
```

The synthetic suite (`scan/synthetic.py`) prints real markup and then degrades it —
blur, skew, JPEG, copier loss, light pencil, crosses. It is what the thresholds were
tuned against, and it is the only honest way to change one.

---

## Companion documents

- [`architecture.md`](architecture.md) — the pipeline in detail, and its edge cases
- [`decisions.md`](decisions.md) — D2, D6, D7, D31, D37, D42
- [`../grading/`](../grading/) — what happens to a `Detection` afterwards

**Last updated:** 2026-09-09
