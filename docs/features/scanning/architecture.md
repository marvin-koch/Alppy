# Scanning Architecture

## Component diagram

```
  api/v1/scans.py            POST /scans  (multipart, sniffed, size-capped)
        │
        ▼
  services/scan_service.py::create_scan
        │  stores bytes, writes Scan + Job(PROCESS_SCAN), returns    ← never blocks
        ▼
  ─────────────────────── arq worker ───────────────────────
  services/scan_processing.py::process_scan
        │
        ├─ _decode_pages ────────────── pypdf / PIL / pillow-heif → Image[]
        │
        ├─ for each page:
        │     detector.process_page(image, option_counts)
        │        ├── find_fiducials   contours, four corner squares
        │        ├── register         perspective transform → 8 px/mm canonical
        │        ├── read_uid_grid    32 cells → bits → CRC-8 → "7B_15"
        │        ├── detect_item(i)   annulus-relative fill + cross score
        │        └── _flag_suspicious_blanks   (page-level distrust)
        │
        ├─ _copies_by_uid       which SheetInstance / page this is    (I-scanning-03)
        ├─ _placements_by_uid   the rectangles the renderer measured  (I-scanning-07)
        ├─ _crop_answer_boxes ─ answer_box.crop_answer_box → encode_png → storage
        ├─ _store_page_image    the REGISTERED page, not the original (I-scanning-10)
        └─ _persist_detections  one Detection per printed item        (I-scanning-08)
        │
        ▼
  Job(GRADE_OPEN_ANSWERS) chained  ──▶ services/open_answer_grading.py  (see grading/)
        │
        ▼
  Scan.status = NEEDS_REVIEW  ──▶  /scans/[id] review overlay
```

## Data flow

### Input

An upload is a pile, not a page: several photos, or one multi-page PDF, become **one**
`Scan`. Accepted types are sniffed from content (`test_upload_rejects_a_file_that_is_not_what_it_claims`),
not read off the declared content type.

### The canonical frame

```python
PX_PER_MM = 8.0          # a 5 mm bubble is 40 px across — enough on a 150 dpi copy
CANONICAL_W = 210 * 8    # every coordinate below is mm from the page's top-left
CANONICAL_H = 297 * 8
```

Registration is the whole trick: after it, a phone photo taken at an angle and a
flatbed scan are the same array, and every later step is a lookup in millimetres.

### Output

```python
@dataclass(frozen=True)
class ItemDetection:
    item_index: int          # page-local 0..15 — the layout's index (I-sheets-06)
    detected_index: int | None
    outcome: DetectionOutcome
    confidence: float

@dataclass(frozen=True)
class PageResult:
    uid: str | None          # None → the page waits for the teacher
    uid_confidence: float
    detections: list[ItemDetection]
```

Persisted as `Detection` rows carrying **both** readings:

| Column | Written by | Written again? |
|---|---|---|
| `machine_index`, `machine_outcome`, `machine_confidence` | the detector, once | **never** (I-scanning-06) |
| `detected_index`, `detected_bool`, `outcome`, `confidence` | the detector, then the teacher | on correction |
| `crop_key`, `transcription`, `verdict_correct` | the crop step, then the vision grader / teacher | see `grading/` |

## Component interaction

### `find_fiducials` / `register`

Binarise, find contours, keep square-ish blobs near the four corners, assign each to
a corner, and solve a perspective transform onto the canonical fiducial centres. It
raises `RegistrationError` for: fewer than four candidates, candidates that collapse
onto one point, a degenerate quadrilateral. **There is no fallback path** — a page
that will not register goes to the teacher (I-scanning-01).

### `detect_item` — fill *and* shape

Two independent measurements per bubble:

- **fill ratio** — dark pixels inside the bubble, relative to a *local annulus* just
  outside it. The annulus is what makes grey photocopy paper and a light pencil both
  readable (D6, I-scanning-04).
- **cross score** — angular structure across `CROSS_BINS` bins, so a student who
  crosses the bubble instead of filling it reads as confidently as one who fills it,
  while a stray line through a bubble does not.

`_mark_strength` combines them. Thresholds: `FILL_MARKED 0.35`, `FILL_BLANK 0.18`,
with `MARGIN_CONFIDENT 0.20` between best and second-best, and `LOW_CONFIDENCE 0.65`
below which the item is surfaced to the teacher first.

### `_flag_suspicious_blanks`

Page-level, and the only place a decision about one item is made from another item.
Above `MOSTLY_BLANK_RATIO` (60 %) blanks among gradeable items, every blank on the
page is downgraded to `LOW_CONFIDENCE`. A student may well leave three quarters of a
sheet empty; a scan that lost a light pencil looks exactly the same per bubble, and
is more common (D7, I-scanning-05).

### `answer_box.crop_answer_box`

Cuts the placement rectangle out of the **registered** page, then paints out Alppy's
own furniture: a band of `EDGE_BAND_MM` at each edge (the border and any corner tick
that leaked inward), and bands of `GUIDE_BAND_MM` at each printed guide — but only
where the pixel is lighter than heavy ink, so a pen stroke crossing a guide survives.
The model is separately told which guides the box carried.

It also answers "is there any ink at all". A box with none is `BLANK` immediately —
no model call, no cost, no risk of a fabricated verdict.

## Edge cases

- **Unreadable UID.** → the page is stored with no student, `Scan.status` reflects it,
  and confirmation is blocked until the teacher assigns it by hand
  (`assign_page_student`, limited to the sheet's own class).
- **A page from another class.** → flagged and not graded.
- **A page printed under another layout version.** → refused (I-scanning-09).
- **A duplicate page (a re-scan).** → supersedes rather than duplicating.
- **A page the teacher discards.** → `set_page_discarded`; it does not block
  confirmation and is not sent to the grader.
- **HEIC from an iPhone.** → decoded via `pillow-heif`; a file merely *claiming* to be
  HEIC is rejected.
- **A corrupt upload.** → `ScanDecodeError`, so the job records an honest failure
  rather than an empty success.
- **An open item on a sheet printed before answer boxes existed.** → no placement, so
  no crop, so `NOT_GRADEABLE` — the old behaviour, not a guessed rectangle.
- **A scanned paper worksheet (no Alppy geometry at all).** → out of scope, and
  refused rather than faked. There is no OCR in the repo (D31).

---

**Companion:** [`README.md`](README.md) §2 for the load-bearing rules.
