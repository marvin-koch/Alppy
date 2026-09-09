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
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.models import (
    AnswerBoxPlacement,
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


def _decode_pages(storage: Storage, scan: Scan) -> list[np.ndarray]:
    """Every page of every file in this upload, in the order they were selected.

    A phone upload is one file per copy: the teacher picks 28 photos and expects
    one review session, so all of them concatenate into this scan's pages.
    """
    keys = list(scan.storage_keys or [scan.storage_key])
    names = _filenames(scan, len(keys))

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


def _placements_by_uid(db: Session, sheet: Sheet | None) -> Placements:
    """uid -> page of the copy (1-based) -> page-local item index -> placement.

    Read straight off the rows the render job wrote, never recomputed: the box
    sits under text the browser wrapped, and the only honest source of where it
    printed is the render that went to the printer (decisions-log D42)."""
    if sheet is None:
        return {}
    out: Placements = {}
    for row in db.execute(
        select(AnswerBoxPlacement).where(AnswerBoxPlacement.sheet_id == sheet.id)
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
    db: Session, *, school_id: uuid.UUID, uid: str | None
) -> Student | None:
    if not uid:
        return None
    return db.execute(
        select(Student).where(Student.school_id == school_id).where(Student.uid == uid)
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


def _persist_detections(
    db: Session,
    *,
    scan: Scan,
    page: ScanPage,
    result: PageResult,
    printed_page: Page | None,
    sheet_items: dict[uuid.UUID, SheetItem],
    crops: dict[int, tuple[str, BoxCrop]] | None = None,
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
    on_progress: ProgressCB | None = None,
) -> dict[str, Any]:
    """Register, read and detect every page of one uploaded scan."""
    scan = db.execute(select(Scan).where(Scan.id == scan_id)).scalar_one_or_none()
    if scan is None:
        raise ValueError(f"no scan {scan_id}")

    scan.status = ScanStatus.PROCESSING
    db.flush()

    try:
        images = _decode_pages(storage, scan)
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

    copies = _copies_by_uid(db, sheet)
    placements = _placements_by_uid(db, sheet)
    sheet_items = _sheet_items_by_exercise(sheet)
    default_counts = [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE

    # How many pages of each student's copy we have already seen. This, and not
    # the index in the upload, is which page of their paper the next one is.
    seen: Counter[str] = Counter()

    registered = 0
    identified = 0
    foreign = 0
    pending = 0
    for index, image in enumerate(images):
        # Pass 1: register and read the printed UID against a full grid. We
        # cannot know which bubbles were printed until we know whose copy this
        # is, and on a differentiated sheet that differs per student.
        result = process_page(image, default_counts, layout_version=layout_version)

        student = _resolve_student(db, school_id=scan.school_id, uid=result.uid)
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
        if printed_pages and result.uid:
            # A copy longer than one page arrives as several scans carrying the
            # same UID. Count per UID: a page whose code did not decode belongs
            # to no copy and must not consume anybody's slot.
            page_in_copy = seen[result.uid] % len(printed_pages)
            seen[result.uid] += 1
            printed_page = printed_pages[page_in_copy]
            # Pass 2: now that the copy is known, look only where its own
            # bubbles actually are.
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
        pending += sum(1 for d in page.detections if d.outcome is DetectionOutcome.PENDING)
        registered += 1 if result.registered else 0
        identified += 1 if result.uid else 0
        foreign += 1 if wrong_class else 0

        if on_progress is not None:
            on_progress(
                (index + 1) / max(1, len(images)),
                f"page {index + 1} of {len(images)}",
            )

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
) -> int:
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
        return 0

    printed_pages = _copies_by_uid(db, sheet).get(student.uid, [])
    if not printed_pages:
        return 0
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
        return 0
    if decoded is None:
        return 0
    image: np.ndarray = decoded.astype(np.uint8)

    layout_version = scan.layout_version or sheet.layout_version or L.LAYOUT_VERSION
    result = process_page(image, printed_page.option_counts, layout_version=layout_version)
    if not result.registered:
        return 0

    for stale in list(page.detections):
        db.delete(stale)
    db.flush()

    page.page_in_copy = index
    crops = _crop_answer_boxes(
        storage,
        scan=scan,
        page_index=page.page_index,
        result=result,
        placements=_placements_by_uid(db, sheet).get(student.uid, {}).get(index + 1, {}),
    )
    _persist_detections(
        db,
        scan=scan,
        page=page,
        result=result,
        printed_page=printed_page,
        sheet_items=_sheet_items_by_exercise(sheet),
        crops=crops,
    )
    return len(result.detections)


def _store_page_image(storage: Storage, key: str, image: np.ndarray | None) -> None:
    import cv2

    if image is None:  # pragma: no cover - registered pages always carry one
        return
    ok, buf = cv2.imencode(".png", image)
    if ok:
        storage.put_bytes(key, buf.tobytes(), "image/png")
