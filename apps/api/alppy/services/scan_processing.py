"""Turning an uploaded scan into reviewable detections.

This is the stage between the teacher dropping a pile of photos on the upload
screen and the review UI having something to show: decode the upload into page
images, register each page against the four corner fiducials, read the printed
UID, detect the marks, and persist one ``Detection`` per item.

It deliberately does **not** grade anything. Grading happens on confirm, after a
human has looked at the low-confidence items — nothing reaches the mastery model
until a teacher signs it off.

Runs in the arq worker: registration and detection are CPU-bound OpenCV work and
must never block a request handler.

Three things here are load-bearing and were each got wrong once:

* **A page belongs to a copy, and a copy belongs to a student.** Which page of
  whose copy is resolved from the *decoded UID*, never from the position in the
  upload — one unreadable photo in the pile used to shift every copy behind it
  and grade a whole class against the wrong questions.
* **An item belongs to the paper it was printed on.** A differentiated copy
  prints its own item list, so the exercise is resolved through that copy's
  pagination and stored on the row, not re-derived from a position in the
  sheet's class-wide list.
* **The machine's reading is written once.** ``machine_*`` is what the detector
  saw; a teacher override later goes into ``detected_*`` beside it.

A written answer is not read here either. Its box is *cut* from the registered
page at the rectangle the renderer measured for this copy — never recomputed
from the rows — stored beside the page image, and the detection is left
``PENDING`` for the vision grader that the worker chains after this job. A box
with no ink in it is a ``BLANK`` straight away; a sheet printed before boxes
existed has no placements and its open items stay ``NOT_GRADEABLE`` as before.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.core.config import get_settings
from alppy.core.logging import get_logger
from alppy.models import (
    AnswerBoxPlacement,
    Class,
    Detection,
    Scan,
    ScanPage,
    Sheet,
    SheetInstance,
    SheetItem,
    Student,
)
from alppy.models.enums import DetectionOutcome, ExerciseType, ScanStatus
from alppy.scan.answer_box import BoxCrop, BoxRect, crop_answer_box, encode_png
from alppy.scan.detector import PageResult, process_page
from alppy.sheets import layout as L
from alppy.sheets.pagination import Page, paginate
from alppy.sheets.render import build_sheet_data
from alppy.storage import Storage, storage_key

log = get_logger(__name__)

ProgressCB = Callable[[float, "str | None"], None]

# A scan of a class set is one file with many pages; a phone upload is one page
# at a time. Both arrive here as a list of images.
MAX_PAGES = 200

#: Page-level warnings, as codes. They are **flags, never blocks**: each one
#: describes a pile that is probably fine and might not be, and a teacher with
#: 28 copies to get through must be able to look and dismiss rather than be
#: stopped. Codes, not sentences, because the client owns the wording (D86).
#:
#: * ``extra_page`` — this copy already had all its pages before this one
#:   arrived. Until B5 the count wrapped with ``%``, so the 3rd photo of a
#:   2-page copy was silently read as page 1 and its answers graded against
#:   page 1's questions. The page is now left unpaired instead.
#: * ``short_copy`` — fewer pages came back for this UID than were printed for
#:   it. The pages that did arrive are still paired in order, because they
#:   almost always are; but if the *missing* one is page 1 then everything
#:   behind it is shifted, and that is not something to decide silently.
#: * ``duplicate_page`` — two live pages of this pile claim the same slot of
#:   the same copy. Usually a re-shot page the teacher has not discarded yet,
#:   which is exactly why it must stay dismissible.
#: * ``printed_after_photo`` — the sheet was re-rendered after this photo was
#:   taken, so the geometry the crops were cut at may not be the geometry this
#:   copy was printed with (B7's interim mitigation, until placements are
#:   pinned to a render generation).
FLAG_EXTRA_PAGE = "extra_page"
FLAG_SHORT_COPY = "short_copy"
FLAG_DUPLICATE_PAGE = "duplicate_page"
FLAG_PRINTED_AFTER_PHOTO = "printed_after_photo"


def _later_than(a: datetime | None, b: datetime | None) -> bool:
    """``a > b``, without caring which of them remembers its timezone.

    Both columns are ``DateTime(timezone=True)`` and both are aware on
    Postgres. The suite runs on SQLite (D18), which has no timezone type and
    hands back naive values — so comparing them directly raises
    ``TypeError: can't compare offset-naive and offset-aware datetimes``
    *inside the scan job*, taking down the processing of a whole pile to
    decide whether to show a warning. A naive value is read as UTC, which is
    what every writer in this codebase stores.

    Either side missing means the question cannot be answered, and an
    unanswerable warning is not a warning.
    """
    if a is None or b is None:
        return False
    if a.tzinfo is None:
        a = a.replace(tzinfo=UTC)
    if b.tzinfo is None:
        b = b.replace(tzinfo=UTC)
    return a > b


def _add_flag(page: ScanPage, flag: str) -> None:
    """Append a warning to a page, keeping the list unique and ordered.

    ``registration_meta`` is JSONB and already the page's own scratch space, so
    this needs no migration — but it is a mutable JSON column, and SQLAlchemy
    does not track in-place mutation of one. The dict is therefore rebuilt and
    reassigned rather than updated in place, which is the difference between a
    flag that reaches the teacher and one that is silently dropped at commit.
    """
    meta = dict(page.registration_meta or {})
    flags = list(meta.get("flags") or [])
    if flag not in flags:
        flags.append(flag)
    meta["flags"] = flags
    page.registration_meta = meta


class ScanDecodeError(ValueError):
    """The upload could not be turned into page images.

    Raised rather than returned. The worker records a job failure from the
    exception; returning a result dict made the job report *success* while the
    scan sat in ``FAILED``, so a client polling the job saw a green tick and
    then an empty review screen.
    """


def _decode_one(data: bytes, filename: str, *, budget: int) -> list[np.ndarray]:
    """Decode a single uploaded file into greyscale page images.

    A PDF is rasterised at 200 dpi — enough to resolve a 5 mm bubble comfortably
    while keeping a 30-page class set to a sane amount of memory.
    """
    import cv2

    if filename.lower().endswith(".pdf"):
        import fitz  # PyMuPDF

        pages: list[np.ndarray] = []
        try:
            with fitz.open(stream=data, filetype="pdf") as doc:
                total = doc.page_count
                for page in doc[:budget]:
                    # The PDF equivalent of the upload guard (audit 03, B15).
                    # A PDF declares its page size, and `get_pixmap` allocates
                    # width x height x dpi^2 / 72^2 bytes from it — a page
                    # claiming 200 x 200 inches is a 3 GB raster from a file of
                    # a few kilobytes. The byte cap never sees it, because the
                    # bytes really are few.
                    _refuse_oversized_page(page, filename=filename)
                    pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
                    buf = np.frombuffer(pix.samples, dtype=np.uint8)
                    pages.append(buf.reshape(pix.height, pix.width).copy())
        except ScanDecodeError:
            raise
        except Exception as exc:  # PyMuPDF raises a wide variety of its own
            raise ScanDecodeError(
                f"{filename} is not a readable PDF (it may be corrupt or password-protected)"
            ) from exc
        if not pages:
            raise ScanDecodeError(f"{filename} contains no pages")
        if total > budget:
            log.warning("scan.pages_truncated", filename=filename, total=total, kept=budget)
        return pages

    buf = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if image is None:
        image = _decode_heif(data)
    if image is None:
        raise ScanDecodeError(f"{filename} is not a readable image")
    return [image]


def _refuse_oversized_page(page: Any, *, filename: str) -> None:
    """Refuse a PDF page whose declared size would rasterise to an absurd image.

    Raised as a ``ScanDecodeError`` so it reaches the teacher through the
    ordinary "this file could not be read" path rather than killing the worker
    — the pile is one bad file, and the other twenty-seven copies are fine.
    """
    rect = page.rect
    scale = 200 / 72  # the dpi `get_pixmap` is called with, in points
    pixels = int(abs(rect.width) * scale) * int(abs(rect.height) * scale)
    ceiling = get_settings().max_image_pixels
    if pixels > ceiling:
        raise ScanDecodeError(
            f"{filename} has a page too large to rasterise "
            f"({int(abs(rect.width))}x{int(abs(rect.height))} pt)"
        )


def _decode_heif(data: bytes) -> np.ndarray | None:
    """HEIC/HEIF, which OpenCV does not read.

    An iPhone photographs in HEIC unless it is told otherwise, so a teacher
    photographing the pile gets a format the rest of the pipeline cannot open.
    Tried only after OpenCV has declined, so nothing else pays for it.
    """
    import io

    try:
        import pillow_heif
        from PIL import Image as PilImage

        # pillow-heif ships no re-export marker for this, and mypy is strict.
        pillow_heif.register_heif_opener()  # type: ignore[attr-defined]  # unmarked re-export
        with PilImage.open(io.BytesIO(data)) as im:
            return np.asarray(im.convert("L"), dtype=np.uint8)
    except Exception as exc:
        log.info("scan.heif_decode_failed", error=str(exc))
        return None


def _decode_pages(storage: Storage, scan: Scan, *, from_file: int = 0) -> list[np.ndarray]:
    """Every page of every file in this upload, in the order they were selected.

    A phone upload is one file per copy: the teacher picks 28 photos and expects
    one review session, so all of them concatenate into this scan's pages.

    ``from_file`` skips the files already read. A page that would not register
    can be re-photographed INTO its own pile rather than into a second one
    (F11), which means processing a scan that already has pages — and reading
    the whole upload again would give every earlier photograph a second
    `ScanPage`, since nothing here deletes what a previous run wrote.
    """
    # Named across the WHOLE upload, then sliced with the keys: `_filenames`
    # pairs `original_filename`'s comma-joined parts with the files in order,
    # so asking it for a slice's length would hand the first new photo the
    # first photo's name.
    all_keys = list(scan.storage_keys or [scan.storage_key])
    keys = all_keys[from_file:]
    names = _filenames(scan, len(all_keys))[from_file:]

    pages: list[np.ndarray] = []
    for key, name in zip(keys, names, strict=True):
        if len(pages) >= MAX_PAGES:
            log.warning("scan.pages_truncated", scan_id=str(scan.id), kept=MAX_PAGES)
            break
        pages.extend(_decode_one(storage.get_bytes(key), name, budget=MAX_PAGES - len(pages)))
    if not pages:
        raise ScanDecodeError("the upload contained no pages")
    return pages


def _filenames(scan: Scan, count: int) -> list[str]:
    """One name per stored file. ``original_filename`` holds them comma-joined
    when several were uploaded together, and falls back to the key's own suffix
    so a PDF is still recognised as one."""
    parts = [p.strip() for p in (scan.original_filename or "").split(",") if p.strip()]
    if len(parts) == count:
        return parts
    keys = list(scan.storage_keys or [scan.storage_key])
    return [keys[i].rsplit("/", 1)[-1] for i in range(count)]


def _copies_by_uid(db: Session, sheet: Sheet | None) -> dict[str, list[Page]]:
    """The pagination of every printed copy, keyed by student UID.

    Keyed by UID rather than computed once, because **a differentiated batch
    gives each student a different item list** (F4): copy 7B_03 may have four
    MCQs where 7B_07 has two true/false items, so "how many bubbles are on row
    3" has a different answer per copy. Using one copy's layout for the whole
    pile would look for bubbles that were never printed.

    Each ``PlacedItem`` carries its own exercise id (``Item.key``), which is how
    a detection is paired with the question the student actually answered.
    """
    if sheet is None:
        # No sheet was named on upload. A full grid is assumed and the
        # confidence model sorts out which positions were actually printed.
        return {}
    data = build_sheet_data(db, sheet)
    return {copy.uid: list(paginate(list(copy.items))) for copy in data.copies}


Placements = dict[str, dict[int, dict[int, AnswerBoxPlacement]]]


def _placements_by_uid(
    db: Session, sheet: Sheet | None, *, generation: int | None
) -> Placements:
    """uid -> page of the copy (1-based) -> page-local item index -> placement.

    Read straight off the rows the render job wrote, never recomputed: the box
    sits under text the browser wrapped, and the only honest source of where it
    printed is the render that went to the printer (decisions-log D42).

    ``generation`` is the render the pile in hand was printed from, pinned on
    the ``Scan`` at upload — **not** the sheet's current one (B7). A sheet
    re-rendered between the printing and the photographing has a newer
    generation whose rectangles describe a different document, and cropping
    Tuesday's copies at Wednesday's rows is how a written answer gets graded on
    whatever ink the crop happened to catch.

    It is a required keyword and NULL is a real value: a pile uploaded before
    generations existed matches the rows that also carry NULL. If that sheet has
    since been re-rendered, nothing matches, and the open items stay
    ``NOT_GRADEABLE`` — no crop, no verdict, counted as skipped. The pipeline
    already handles a missing crop and has no way to handle a wrong one.
    """
    if sheet is None:
        return {}
    out: Placements = {}
    for row in db.execute(
        select(AnswerBoxPlacement)
        .where(AnswerBoxPlacement.sheet_id == sheet.id)
        .where(
            AnswerBoxPlacement.render_generation.is_(None)
            if generation is None
            else AnswerBoxPlacement.render_generation == generation
        )
    ).scalars():
        out.setdefault(row.student_uid, {}).setdefault(row.copy_page, {})[row.item_index] = row
    return out


def _crop_answer_boxes(
    storage: Storage,
    *,
    scan: Scan,
    page_index: int,
    result: PageResult,
    placements: dict[int, AnswerBoxPlacement],
) -> dict[int, tuple[str, BoxCrop]]:
    """Cut every placed box out of the registered page and store the crops.

    Returns ``item_index -> (storage key, crop)``. A box that cannot be cut —
    a placement off the page, a storage hiccup — is logged and skipped: that
    item then stays ``NOT_GRADEABLE``, which is honest, rather than failing
    the whole pile."""
    if result.canonical is None or not placements:
        return {}
    out: dict[int, tuple[str, BoxCrop]] = {}
    for item_index, placement in placements.items():
        rect = BoxRect(placement.x_mm, placement.y_mm, placement.w_mm, placement.h_mm)
        try:
            crop = crop_answer_box(result.canonical, rect, fill=placement.box_fill)
            key = storage_key(
                "scan-pages", scan.school_id, scan.id, f"page-{page_index:03d}-box-{item_index:02d}.png"
            )
            storage.put_bytes(key, encode_png(crop.image), "image/png")
        except Exception as exc:
            log.warning(
                "scan.box_crop_failed",
                scan_id=str(scan.id),
                page_index=page_index,
                item_index=item_index,
                error=str(exc),
            )
            continue
        out[item_index] = (key, crop)
    return out


def _resolve_student(
    db: Session,
    *,
    school_id: uuid.UUID,
    uid: str | None,
    school_year_id: uuid.UUID | None,
) -> Student | None:
    """The pupil a decoded UID names, within ONE school year.

    ``uq_student_uid`` is ``(school_id, school_year_id, uid)`` — a UID is a fact
    about one year's paper, not about a person (0028, D87). Matching on
    ``(school_id, uid)`` alone therefore has no unique index under it, and only
    resolved because every school in existence has had exactly one
    ``SchoolYear`` row. The second one does not arrive at rollover: it arrives
    in June, when a school starts preparing next year's classes while this year
    is still running and marking. From that day `10VG3_07` names two pupils and
    this read raises ``MultipleResultsFound`` in the middle of a scan job.

    ``school_year_id`` is a **required keyword with no default**, and NULL is a
    real value meaning "no year to scope to" rather than "any year" — the same
    device 0027 used for ``on``, for the same reason: a default would let a new
    call site compile while quietly asking the unscoped question again.

    **``scalar_one_or_none`` stays.** The loud failure is the good outcome. A
    ``.first()`` here would convert a total-but-visible outage into a silent
    cross-year misattribution — one child's answers filed under another child's
    name, with nothing anywhere saying so — which is the worst failure this
    system has. Do not relax it.
    """
    if not uid or school_year_id is None:
        # No sheet on the pile means no class, so no year (`Scan.sheet_id` is
        # nullable and detaches on ondelete="SET NULL"). There is no safe way
        # to guess which year's `10VG3_07` this is, so the page is left for
        # manual assignment — the same answer `assignable_students` already
        # gives for the same case, rather than a guess that reads as a fact.
        return None
    return db.execute(
        select(Student)
        .where(Student.school_id == school_id)
        .where(Student.school_year_id == school_year_id)
        .where(Student.uid == uid)
    ).scalar_one_or_none()


def _sheet_items_by_exercise(sheet: Sheet | None) -> dict[uuid.UUID, SheetItem]:
    if sheet is None:
        return {}
    return {si.exercise_id: si for si in sheet.items}


def _persist_page(
    db: Session,
    *,
    scan: Scan,
    page_index: int,
    image_key: str,
    result: PageResult,
    sheet: Sheet | None,
    student: Student | None,
    wrong_class: bool,
    printed_page: Page | None,
    page_in_copy: int | None,
    sheet_items: dict[uuid.UUID, SheetItem],
    crops: dict[int, tuple[str, BoxCrop]] | None = None,
) -> ScanPage:
    instance: SheetInstance | None = None
    if sheet is not None and student is not None and not wrong_class:
        instance = db.execute(
            select(SheetInstance)
            .where(SheetInstance.sheet_id == sheet.id)
            .where(SheetInstance.student_id == student.id)
        ).scalar_one_or_none()

    page = ScanPage(
        id=uuid.uuid4(),
        school_id=scan.school_id,
        scan_id=scan.id,
        page_index=page_index,
        image_key=image_key,
        registered=result.registered,
        registration_meta={
            "skew_deg": round(result.skew_deg, 3),
            "quality": round(result.quality, 3),
            "error": result.error,
        },
        detected_uid=result.uid,
        uid_confidence=result.uid_confidence,
        student_id=student.id if student else None,
        sheet_instance_id=instance.id if instance else None,
        wrong_class=wrong_class,
        page_in_copy=page_in_copy,
    )
    db.add(page)
    db.flush()
    _persist_detections(
        db, scan=scan, page=page, result=result,
        printed_page=printed_page, sheet_items=sheet_items, crops=crops,
    )
    return page


@dataclass(frozen=True)
class RedetectResult:
    """What re-reading one page did.

    ``corrections_dropped`` carries the numbers, as printed on the paper, of
    the teacher's own corrections that the new reading had nowhere to put —
    corrections to items this copy turns out not to have. It is a list rather
    than a count because the teacher needs to know *which* answers to look at
    again, and it is returned rather than logged only because the person who
    needs it is looking at the review screen, not at the log (audit 03, B6).
    """

    detections: int
    corrections_dropped: tuple[int, ...] = ()

    @classmethod
    def none(cls) -> RedetectResult:
        """Nothing was re-read, so nothing was lost.

        Re-reading is a bonus and never a precondition — a missing page image
        must not make naming the pupil fail — so every early return here means
        the detections on the page are untouched, corrections included.
        """
        return cls(detections=0)


class _CarriedCorrections:
    """The teacher's overrides from a previous reading of one page, waiting to
    be re-attached to the reading that replaces it.

    **Filed by exercise, not by slot**, and that is the whole point of the
    class. A correction says "I looked at this mark and it is a B" about a
    *question*; the slot it sat in is an accident of how the copy paginated.
    Re-reading a page against a different copy — which is exactly what
    re-assigning it does — can move the same exercise from item 3 to item 5,
    and a slot-keyed lookup then finds nothing and drops a correction the
    teacher made by hand (audit 03, B6).

    Two indexes because a correction can predate pairing. A page whose UID
    never decoded is read against the full default grid and its detections
    carry no ``exercise_id`` at all, yet a teacher can still fix the bubbles on
    it before naming the pupil. Those rows are filed by slot, because slot is
    the only thing they know — and matching them by slot is sound for the same
    reason matching a paired row by slot is not: it is the *same image*, so the
    ink at position 3 is the ink at position 3. What changes between readings
    is which question the copy says was printed there.

    A row is filed under exactly one key, so ``take`` can never hand the same
    correction to two detections.
    """

    def __init__(self, rows: Iterable[Detection]) -> None:
        self.by_exercise: dict[uuid.UUID, Detection] = {}
        self.by_index: dict[int, Detection] = {}
        for row in rows:
            if row.exercise_id is not None:
                self.by_exercise[row.exercise_id] = row
            else:
                self.by_index[row.item_index] = row

    def take(
        self, *, exercise_id: uuid.UUID | None, item_index: int
    ) -> Detection | None:
        """The correction that belongs to this reading, removed from the pool.

        Exercise first. The slot fallback only ever reaches a row that was
        never paired, since a paired row is filed under its exercise — so a
        verdict about question Y can never be handed to question X merely
        because they printed in the same position.
        """
        if exercise_id is not None:
            row = self.by_exercise.pop(exercise_id, None)
            if row is not None:
                return row
        return self.by_index.pop(item_index, None)

    def orphans(self) -> list[Detection]:
        """What nothing on the new reading claimed.

        Corrections to items this copy turns out not to have. The caller
        deletes them and tells the teacher which ones, by the number printed on
        the paper — silently discarding a correction someone made by hand is
        how eleven fixed bubbles disappear with no error anywhere.
        """
        return [*self.by_exercise.values(), *self.by_index.values()]


def _persist_detections(
    db: Session,
    *,
    scan: Scan,
    page: ScanPage,
    result: PageResult,
    printed_page: Page | None,
    sheet_items: dict[uuid.UUID, SheetItem],
    crops: dict[int, tuple[str, BoxCrop]] | None = None,
    corrected: _CarriedCorrections | None = None,
) -> int:
    """One ``Detection`` per item read on this page. Returns how many were left
    ``PENDING`` for the vision grader.

    Pair each with the exercise printed at that position ON THIS COPY.
    ``printed_page`` is this student's own pagination, so a differentiated copy
    resolves to its own questions rather than to whatever sits at the same index
    of the class-wide list.

    A written answer whose box was cut (``crops``) is stored with its crop and
    left ``PENDING`` — or ``BLANK`` when the crop holds no ink, which needs no
    model to say. Without a crop it stays ``NOT_GRADEABLE``, exactly as before.

    ``corrected`` carries the rows a teacher has already overridden, by item
    index, for a page being read a second time. A correction is a fact about
    the ink on the paper — the teacher looked at the mark and said what it is —
    so it survives the re-reading of the page it is written on, and only the
    ``machine_*`` columns beneath it are refreshed. It does NOT survive the
    exercise at that position changing: on a differentiated copy the same index
    can hold a different question, and a verdict about one question is not a
    verdict about another. Rows left unconsumed are the teacher's corrections
    to items this copy turns out not to have, and the caller deletes them.
    """
    placed = {p.item_index: p for p in printed_page.items} if printed_page else {}
    pending = 0

    for detection in result.detections:
        outcome = detection.outcome
        confidence = detection.confidence
        crop_key: str | None = None
        cropped = (crops or {}).get(detection.item_index)
        if cropped is not None and outcome is DetectionOutcome.NOT_GRADEABLE:
            crop_key, crop = cropped
            if crop.blank:
                outcome = DetectionOutcome.BLANK
                confidence = crop.blank_confidence
            else:
                outcome = DetectionOutcome.PENDING
                confidence = 0.0
                pending += 1

        exercise_id: uuid.UUID | None = None
        sheet_item_id: uuid.UUID | None = None
        placed_item = placed.get(detection.item_index)
        if placed_item is not None and placed_item.part == "statement":
            # The statement of a split item: its box, and so its reading, is
            # the continuation on the next page. A row here would be a second
            # detection of the same exercise, never gradeable, shown to the
            # teacher as an unreadable answer that was never asked for.
            continue
        if placed_item is not None:
            try:
                exercise_id = uuid.UUID(placed_item.item.key)
            except (ValueError, AttributeError):  # pragma: no cover - defensive
                exercise_id = None
            if exercise_id is not None:
                sheet_item = sheet_items.get(exercise_id)
                sheet_item_id = sheet_item.id if sheet_item else None

        kept = (
            corrected.take(exercise_id=exercise_id, item_index=detection.item_index)
            if corrected is not None
            else None
        )
        if kept is not None:
            # The teacher's reading stands; only what the machine says under it
            # is refreshed. `detected_*`, `outcome`, `confidence`,
            # `verdict_correct`, `transcription`, `corrected_at` and
            # `corrected_by_id` are all left exactly as they were.
            kept.machine_index = detection.detected_index
            kept.machine_outcome = outcome
            kept.machine_confidence = confidence
            kept.fill_ratios = detection.fill_ratios or None
            kept.bubble_boxes = detection.bubble_boxes or None
            kept.sheet_item_id = sheet_item_id
            kept.printed_number = placed_item.number if placed_item else None
            # The row follows the exercise to wherever this copy printed it.
            # Both columns are rewritten because a slot-keyed match is no
            # longer what found it: the correction may be arriving from
            # another position entirely, or from a reading that had no
            # exercise at all because the UID had not decoded yet.
            kept.item_index = detection.item_index
            kept.exercise_id = exercise_id
            if crop_key is not None:
                kept.crop_key = crop_key
            continue

        db.add(
            Detection(
                id=uuid.uuid4(),
                school_id=scan.school_id,
                scan_page_id=page.id,
                sheet_item_id=sheet_item_id,
                exercise_id=exercise_id,
                item_index=detection.item_index,
                printed_number=placed_item.number if placed_item else None,
                detected_index=detection.detected_index,
                detected_bool=_detected_bool(placed_item, detection.detected_index),
                confidence=confidence,
                outcome=outcome,
                # Written once. A teacher override later changes the columns
                # above and leaves these three alone.
                machine_index=detection.detected_index,
                machine_outcome=outcome,
                machine_confidence=confidence,
                fill_ratios=detection.fill_ratios or None,
                bubble_boxes=detection.bubble_boxes or None,
                crop_key=crop_key,
            )
        )
    return pending


def _flag_incomplete_copies(
    db: Session,
    scan: Scan,
    *,
    copies: dict[str, list[Page]],
    seen: Counter[str],
) -> None:
    """Two things only the finished pile can say (B5).

    **A copy that came back short.** Fewer pages arrived for this UID than were
    printed for it. The pages that did arrive are left paired, because they
    arrive in order almost every time and un-pairing them would throw away
    good readings to guard against a rarer fault — but if the page that went
    missing is page *1*, every page behind it has shifted up a slot and been
    read against the wrong questions. That is not a thing to decide on the
    teacher's behalf in silence, so the copy is flagged and they can look.

    The duplicate-slot half is `_flag_duplicate_slots`, which runs here and
    again after a manual assignment — see its own note for why that second
    call is where it actually earns its keep.
    """
    live = _live_pages(db, scan)
    for page in live:
        uid = page.detected_uid
        if not uid:
            continue
        printed = len(copies.get(uid, []))
        if printed and seen.get(uid, 0) < printed:
            _add_flag(page, FLAG_SHORT_COPY)
    _flag_duplicate_slots(db, scan)


def _live_pages(db: Session, scan: Scan) -> list[ScanPage]:
    """The pages still in this pile, as rows.

    Queried, never `scan.pages`. `Scan.pages` and `ScanPage.detections` are both
    `delete-orphan` collections, and `_persist_detections` attaches its rows by
    foreign key rather than by appending to the collection. Touching the
    relationship during processing materialises it as EMPTY — the rows are in
    the database but were never put in the list — and the next flush then
    deletes every detection on the page as an orphan. A warning sweep that
    destroys a whole pile of readings is a spectacular way to lose a class's
    marks, so this walks rows and not relationships.

    Discarded and foreign pages are excluded: both are already out of the pile.
    """
    return list(
        db.execute(
            select(ScanPage)
            .where(ScanPage.scan_id == scan.id)
            .where(ScanPage.discarded.is_(False))
            .where(ScanPage.wrong_class.is_(False))
        ).scalars()
    )


def _flag_duplicate_slots(db: Session, scan: Scan) -> None:
    """Two live pages of one pile claiming the same slot of the same copy.

    Unreachable from processing alone since B5 — an extra page is now left
    unpaired rather than wrapped round onto slot 0 — and very reachable the way
    it actually happens: the teacher assigns that unpaired re-shot page by hand,
    `redetect_page` gives it slot 0, and the blurred original is still sitting
    in the pile holding the same slot. So this runs after a manual assignment
    too, which is the call that matters.

    It flags and never blocks. Discarding the bad photo is one click, and being
    unable to confirm 27 good copies because of it is exactly the failure
    `set_page_discarded` was written to end.
    """
    slots: dict[tuple[str, int], list[ScanPage]] = {}
    for page in _live_pages(db, scan):
        if page.detected_uid and page.page_in_copy is not None:
            slots.setdefault((page.detected_uid, page.page_in_copy), []).append(page)
    for sharing in slots.values():
        if len(sharing) > 1:
            for page in sharing:
                _add_flag(page, FLAG_DUPLICATE_PAGE)


def _detected_bool(placed_item: Any, detected_index: int | None) -> bool | None:
    """Only a true/false item has a boolean reading.

    An MCQ answered "C" used to carry ``detected_bool = False``, which is not
    false, it is meaningless — bubble 0 is only "true" on a two-option item.
    """
    if detected_index is None or placed_item is None:
        return None
    if placed_item.item.type is not ExerciseType.TRUE_FALSE:
        return None
    return detected_index == 0


def process_scan(
    db: Session,
    storage: Storage,
    *,
    scan_id: uuid.UUID,
    from_file: int = 0,
    on_progress: ProgressCB | None = None,
) -> dict[str, Any]:
    """Register, read and detect every page of one uploaded scan.

    ``from_file`` processes only the files added since — the re-shot page that
    joins a pile it already belongs to (F11). Nothing here deletes a previous
    run's `ScanPage` rows, deliberately: the teacher's corrections hang off
    them. So a partial run must add the new photographs and leave everything
    already read exactly as it is, including whatever has since been corrected
    by hand.
    """
    scan = db.execute(select(Scan).where(Scan.id == scan_id)).scalar_one_or_none()
    if scan is None:
        raise ValueError(f"no scan {scan_id}")

    scan.status = ScanStatus.PROCESSING
    db.flush()

    try:
        images = _decode_pages(storage, scan, from_file=from_file)
    except Exception as exc:
        scan.status = ScanStatus.FAILED
        scan.error = str(exc) if isinstance(exc, ScanDecodeError) else "could not read the upload"
        db.commit()
        log.warning("scan.decode_failed", scan_id=str(scan_id), error=str(exc))
        # Raise: the job must record a failure, not a success with an error in
        # its result payload.
        raise ScanDecodeError(scan.error) from exc

    sheet = (
        db.execute(select(Sheet).where(Sheet.id == scan.sheet_id)).scalar_one_or_none()
        if scan.sheet_id
        else None
    )
    # The layout a page must be registered against is the one it was PRINTED
    # with, which travels on the sheet — never whatever the code implements now.
    layout_version = scan.layout_version or (sheet.layout_version if sheet else None)
    layout_version = layout_version or L.LAYOUT_VERSION

    # The year a decoded UID is read in, resolved through the paper rather than
    # through the clock: `Sheet -> Class -> school_year_id`. A pile photographed
    # in June may hold copies printed in October, and the year that matters is
    # the one the class sat, not the one the school is currently preparing (B3).
    school_year_id = (
        db.execute(select(Class.school_year_id).where(Class.id == sheet.class_id)).scalar_one()
        if sheet is not None
        else None
    )

    # B7's interim mitigation, and it is only that. `_persist_answer_box_placements`
    # deletes and rewrites every rectangle on EVERY render, so a sheet printed on
    # Tuesday, edited and re-rendered on Wednesday for an absentee, and
    # photographed on Thursday has its Tuesday copies cropped at Wednesday's
    # geometry. Nothing here can repair that — the Tuesday rectangles are gone —
    # but a pile whose sheet was re-rendered after the photographs were taken is
    # exactly the pile where a written answer may have been cut at the wrong
    # rows, and saying so costs one comparison. The real fix pins placements to
    # a render generation and is still open.
    printed_after_photo = _later_than(
        sheet.rendered_at if sheet is not None else None, scan.created_at
    )

    copies = _copies_by_uid(db, sheet)
    # The generation this pile was PRINTED from, pinned at upload.
    placements = _placements_by_uid(db, sheet, generation=scan.render_generation)
    sheet_items = _sheet_items_by_exercise(sheet)
    default_counts = [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE

    # How many pages of each student's copy we have already seen. This, and not
    # the index in the upload, is which page of their paper the next one is.
    #
    # Seeded from the rows a previous run wrote, because on a partial run they
    # are exactly the pages "already seen". Starting from zero would place a
    # re-shot page 2 into slot 0 and read it against page 1's option counts —
    # the same class of error as the modulo B5 removed, arriving by a different
    # door. Discarded rows are excluded: discarding the blurred original is how
    # a teacher says "that photograph is not one of this copy's pages", and it
    # is the move that makes an overflowed pile ordinary again.
    seen: Counter[str] = Counter()
    if from_file > 0:
        for uid, count in db.execute(
            select(ScanPage.detected_uid, func.count())
            .where(ScanPage.scan_id == scan.id)
            .where(ScanPage.discarded.is_(False))
            .where(ScanPage.detected_uid.is_not(None))
            .group_by(ScanPage.detected_uid)
        ).all():
            seen[str(uid)] = int(count)

    registered = 0
    identified = 0
    foreign = 0
    pending = 0
    # Where this run's pages start. `index` is BOTH the stored `page_index` and
    # the storage key (`page-003.png`), so a partial run that restarted at zero
    # would collide with the rows a previous run wrote and overwrite its
    # registered images in the bucket — the pile would appear to renumber
    # itself, and the review overlay would draw one page's boxes over another's
    # photograph.
    page_offset = (
        int(
            db.execute(
                select(func.count()).select_from(ScanPage).where(ScanPage.scan_id == scan.id)
            ).scalar_one()
        )
        if from_file > 0
        else 0
    )
    for position, image in enumerate(images):
        index = position + page_offset
        # Pass 1: register and read the printed UID against a full grid. We
        # cannot know which bubbles were printed until we know whose copy this
        # is, and on a differentiated sheet that differs per student.
        result = process_page(image, default_counts, layout_version=layout_version)

        student = _resolve_student(
            db, school_id=scan.school_id, uid=result.uid, school_year_id=school_year_id
        )
        # ENROLLMENT, not the home class. A child co-enrolled in this sheet's
        # class sat this paper legitimately; reading `home_class_id` here would
        # flag them foreign and the branch below would then throw away every
        # detection on the page — their answers gone, with no error anywhere
        # (D69, I-platform-09).
        wrong_class = bool(
            student is not None
            and sheet is not None
            and sheet.class_id not in {c.id for c in student.classes}
        )

        if wrong_class:
            # It is someone else's paper. Reading its bubbles against this
            # sheet's grid produces a screenful of phantom low-confidence rows
            # for a page the teacher only needs to be told about.
            result.detections = []

        printed_pages = [] if wrong_class else copies.get(result.uid or "", [])
        page_in_copy: int | None = None
        printed_page: Page | None = None
        overflowed = False
        if printed_pages and result.uid:
            # A copy longer than one page arrives as several scans carrying the
            # same UID. Count per UID: a page whose code did not decode belongs
            # to no copy and must not consume anybody's slot.
            #
            # This used to be `seen[uid] % len(printed_pages)`, and the modulo
            # was the bug (B5). A copy of two pages photographed three times —
            # one page re-shot, the blurred original still in the pile — wrapped
            # the third photo round to slot 0 and read it against page 1's
            # option counts. That is a page of answers graded against the wrong
            # questions, with nothing on the screen saying so.
            #
            # An extra page cannot be placed, so it is not placed: no pairing,
            # no second detection pass, and a flag the teacher can see and
            # dismiss. Discarding the re-shot original then makes the pile
            # ordinary again.
            if seen[result.uid] >= len(printed_pages):
                overflowed = True
                seen[result.uid] += 1
            else:
                page_in_copy = seen[result.uid]
                seen[result.uid] += 1
                printed_page = printed_pages[page_in_copy]
                # Pass 2: now that the copy is known, look only where its own
                # bubbles actually are. An overflowed page never gets here —
                # there is no copy slot to read it against, and reading it
                # against a borrowed one is the misgrading B5 exists to stop.
                result = process_page(
                    image, printed_page.option_counts, layout_version=layout_version
                )

        key = storage_key("scan-pages", scan.school_id, scan.id, f"page-{index:03d}.png")
        # The registered page, not the raw upload: the review overlay draws
        # boxes at the coordinates the detector sampled, and those only line up
        # with the deskewed page. A page that failed to register keeps its
        # original so the teacher can see what went wrong.
        _store_page_image(storage, key, result.canonical if result.registered else image)

        # The written answers: cut where this copy's boxes were measured to
        # have printed. `page_in_copy` counts from 0; the placement's folio
        # counts from 1, as the paper does.
        crops: dict[int, tuple[str, BoxCrop]] = {}
        if result.registered and result.uid and page_in_copy is not None:
            crops = _crop_answer_boxes(
                storage,
                scan=scan,
                page_index=index,
                result=result,
                placements=placements.get(result.uid, {}).get(page_in_copy + 1, {}),
            )

        page = _persist_page(
            db,
            scan=scan,
            page_index=index,
            image_key=key,
            result=result,
            sheet=sheet,
            student=student,
            wrong_class=wrong_class,
            printed_page=printed_page,
            page_in_copy=page_in_copy,
            sheet_items=sheet_items,
            crops=crops,
        )
        if overflowed:
            _add_flag(page, FLAG_EXTRA_PAGE)
        if printed_after_photo:
            _add_flag(page, FLAG_PRINTED_AFTER_PHOTO)
        pending += sum(1 for d in page.detections if d.outcome is DetectionOutcome.PENDING)
        registered += 1 if result.registered else 0
        identified += 1 if result.uid else 0
        foreign += 1 if wrong_class else 0

        if on_progress is not None:
            # `position`, not `index`: progress is a fraction of the work this
            # run was given, and an offset index would report 4/2 pages.
            on_progress(
                (position + 1) / max(1, len(images)),
                f"page {position + 1} of {len(images)}",
            )

    _flag_incomplete_copies(db, scan, copies=copies, seen=seen)

    # Every scan lands in review. Even a page the detector is sure about is the
    # teacher's to confirm — nothing reaches the mastery model unsigned.
    scan.status = ScanStatus.NEEDS_REVIEW
    scan.error = None
    db.commit()

    log.info(
        "scan.processed",
        scan_id=str(scan_id),
        pages=len(images),
        registered=registered,
        identified=identified,
        wrong_class=foreign,
        pending_open_answers=pending,
    )
    return {
        "pages": len(images),
        "registered": registered,
        "identified": identified,
        "wrong_class": foreign,
        # What the worker chains a grading job for. Zero means no job.
        "pending_open_answers": pending,
    }


def redetect_page(
    db: Session, storage: Storage, *, page: ScanPage, student: Student
) -> RedetectResult:
    """Read a page again, now that we know whose copy it is.

    A page whose printed code could not be read is detected against the full
    default grid, because until the copy is known there is no way to tell which
    bubbles were printed — and every reading is left unpaired, since "item 3"
    means nothing without a copy. When the teacher assigns the page by hand,
    that changes: the copy is known, and the readings have to be redone against
    it. Without this the manual fallback produced a page full of detections that
    graded nothing, which is the failure it exists to prevent.

    Returns the number of detections written.
    """
    import cv2

    scan = db.execute(select(Scan).where(Scan.id == page.scan_id)).scalar_one()
    sheet = (
        db.execute(select(Sheet).where(Sheet.id == scan.sheet_id)).scalar_one_or_none()
        if scan.sheet_id
        else None
    )
    if sheet is None or not page.registered:
        return RedetectResult.none()

    printed_pages = _copies_by_uid(db, sheet).get(student.uid, [])
    if not printed_pages:
        return RedetectResult.none()
    index = page.page_in_copy if page.page_in_copy is not None else 0
    printed_page = printed_pages[min(index, len(printed_pages) - 1)]

    # Re-reading is a bonus, never a precondition: naming the student is the
    # part that matters, and a page image that has expired or gone missing must
    # not make the assignment itself fail.
    try:
        raw = np.frombuffer(storage.get_bytes(page.image_key), dtype=np.uint8)
        decoded = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
    except Exception as exc:
        log.warning(
            "scan.redetect_unavailable", page_id=str(page.id), error=str(exc)
        )
        return RedetectResult.none()
    if decoded is None:
        return RedetectResult.none()
    image: np.ndarray = decoded.astype(np.uint8)

    layout_version = scan.layout_version or sheet.layout_version or L.LAYOUT_VERSION
    result = process_page(image, printed_page.option_counts, layout_version=layout_version)
    if not result.registered:
        return RedetectResult.none()

    # A teacher correction is not machine output, and re-reading the page must
    # not throw it away. Re-assigning a page used to delete every Detection on
    # it, corrected rows included, with no way back: the teacher who had fixed
    # eleven misread bubbles lost all eleven by naming the pupil a second time
    # (audit 02, C2).
    # Queried rather than read off `page.detections`. Assigning a page twice in
    # one session — assign away, assign back — leaves the loaded collection
    # holding rows the first pass already deleted, and re-deleting one raises a
    # SAWarning that the DELETE matched nothing. Harmless in itself, but the
    # same staleness decides which corrections are carried, and that is not
    # something to read from a collection that may be a pass behind.
    existing = list(
        db.execute(
            select(Detection).where(Detection.scan_page_id == page.id)
        ).scalars()
    )
    corrected = _CarriedCorrections(d for d in existing if d.corrected_at is not None)
    for stale in existing:
        if stale.corrected_at is None:
            db.delete(stale)
    db.flush()

    page.page_in_copy = index
    crops = _crop_answer_boxes(
        storage,
        scan=scan,
        page_index=page.page_index,
        result=result,
        placements=(
            _placements_by_uid(db, sheet, generation=scan.render_generation)
            .get(student.uid, {})
            .get(index + 1, {})
        ),
    )
    _persist_detections(
        db,
        scan=scan,
        page=page,
        result=result,
        printed_page=printed_page,
        sheet_items=_sheet_items_by_exercise(sheet),
        crops=crops,
        corrected=corrected,
    )
    # Whatever `_persist_detections` did not consume is a correction to an item
    # this copy does not have. It is not still about the paper in front of us —
    # but it was made by hand, so it is reported on the way out rather than
    # vanishing (audit 03, B6). By the number printed on the paper, which is
    # what the teacher will be looking at.
    orphans = corrected.orphans()
    dropped = tuple(
        sorted(o.printed_number if o.printed_number is not None else o.item_index + 1 for o in orphans)
    )
    for orphan in orphans:
        db.delete(orphan)
    db.flush()
    if dropped:
        log.info(
            "scan.corrections_dropped",
            page_id=str(page.id),
            student_uid=student.uid,
            numbers=list(dropped),
        )
    return RedetectResult(detections=len(result.detections), corrections_dropped=dropped)


def _store_page_image(storage: Storage, key: str, image: np.ndarray | None) -> None:
    import cv2

    if image is None:  # pragma: no cover - registered pages always carry one
        return
    ok, buf = cv2.imencode(".png", image)
    if ok:
        storage.put_bytes(key, buf.tobytes(), "image/png")
