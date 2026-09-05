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
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.models import Detection, Scan, ScanPage, Sheet, SheetInstance, Student
from alppy.models.enums import ScanStatus
from alppy.scan.detector import PageResult, process_page
from alppy.sheets import layout as L
from alppy.sheets.pagination import paginate
from alppy.sheets.render import build_sheet_data
from alppy.storage import Storage, storage_key

log = get_logger(__name__)

ProgressCB = Callable[[float, "str | None"], None]

# A scan of a class set is one file with many pages; a phone upload is one page
# at a time. Both arrive here as a list of images.
MAX_PAGES = 200


def _decode_pages(data: bytes, content_type: str) -> list[np.ndarray]:
    """Decode an upload into greyscale page images.

    A PDF is rasterised at 200 dpi — enough to resolve a 5 mm bubble comfortably
    while keeping a 30-page class set to a sane amount of memory.
    """
    import cv2

    if content_type == "application/pdf":
        import fitz  # PyMuPDF

        pages: list[np.ndarray] = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc[:MAX_PAGES]:
                pix = page.get_pixmap(dpi=200, colorspace=fitz.csGRAY)
                buf = np.frombuffer(pix.samples, dtype=np.uint8)
                pages.append(buf.reshape(pix.height, pix.width).copy())
        return pages

    buf = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise ValueError("could not decode the uploaded image")
    return [image]


def _pages_by_uid(db: Session, sheet: Sheet | None) -> dict[str, list[Any]]:
    """The pagination of every printed copy, keyed by student UID.

    Keyed by UID rather than computed once, because **a differentiated batch
    gives each student a different item list** (F4): copy 7B_03 may have four
    MCQs where 7B_07 has two true/false items, so "how many bubbles are on row
    3" has a different answer per copy. Using one copy's layout for the whole
    pile would look for bubbles that were never printed.

    The detector needs nothing else about the content — it addresses bubbles by
    page-local index, so this tells it exactly where to look without reading a
    word of the page.
    """
    if sheet is None:
        # No sheet was named on upload. A full grid is assumed and the
        # confidence model sorts out which positions were actually printed.
        return {}
    data = build_sheet_data(db, sheet)
    return {copy.uid: list(paginate(copy.items)) for copy in data.copies}


def _resolve_student(
    db: Session, *, school_id: uuid.UUID, uid: str | None
) -> Student | None:
    if not uid:
        return None
    return db.execute(
        select(Student).where(Student.school_id == school_id).where(Student.uid == uid)
    ).scalar_one_or_none()


def _persist_page(
    db: Session,
    *,
    scan: Scan,
    page_index: int,
    image_key: str,
    result: PageResult,
    sheet: Sheet | None,
    printed_pages: list[Any],
    page_in_copy: int,
) -> ScanPage:
    student = _resolve_student(db, school_id=scan.school_id, uid=result.uid)

    instance: SheetInstance | None = None
    if sheet is not None and student is not None:
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
    )
    db.add(page)
    db.flush()

    # Pair detections with the sheet items that were printed on this page, so
    # the review UI can show the statement next to the mark it read.
    sheet_items = list(sheet.items) if sheet is not None else []
    placed = (
        {p.item_index: p for p in printed_pages[page_in_copy].items}
        if page_in_copy < len(printed_pages)
        else {}
    )

    for detection in result.detections:
        placed_item = placed.get(detection.item_index)
        sheet_item_id = None
        if placed_item is not None and placed_item.number - 1 < len(sheet_items):
            sheet_item_id = sheet_items[placed_item.number - 1].id
        db.add(
            Detection(
                id=uuid.uuid4(),
                school_id=scan.school_id,
                scan_page_id=page.id,
                sheet_item_id=sheet_item_id,
                item_index=detection.item_index,
                detected_index=detection.detected_index,
                detected_bool=(
                    None
                    if detection.detected_index is None
                    else detection.detected_index == 0
                ),
                confidence=detection.confidence,
                outcome=detection.outcome,
                fill_ratios=detection.fill_ratios or None,
                bubble_boxes=detection.bubble_boxes or None,
            )
        )
    return page


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
        images = _decode_pages(storage.get_bytes(scan.storage_key), _content_type(scan))
    except Exception as exc:
        scan.status = ScanStatus.FAILED
        scan.error = f"could not read the upload: {exc}"
        db.commit()
        log.warning("scan.decode_failed", scan_id=str(scan_id), error=str(exc))
        return {"pages": 0, "registered": 0, "error": scan.error}

    sheet = (
        db.execute(select(Sheet).where(Sheet.id == scan.sheet_id)).scalar_one_or_none()
        if scan.sheet_id
        else None
    )
    pages_by_uid = _pages_by_uid(db, sheet)
    default_counts = [L.MAX_OPTIONS] * L.ITEMS_PER_PAGE

    registered = 0
    identified = 0
    for index, image in enumerate(images):
        # Pass 1: register and read the printed UID against a full grid. We
        # cannot know which bubbles were printed until we know whose copy this
        # is, and on a differentiated sheet that differs per student.
        result = process_page(image, default_counts)

        printed_pages = pages_by_uid.get(result.uid or "", [])
        page_in_copy = _page_within_copy(index, images_seen=index, pages=printed_pages)

        if printed_pages and page_in_copy < len(printed_pages):
            # Pass 2: now that the copy is known, look only where its own
            # bubbles actually are.
            result = process_page(image, printed_pages[page_in_copy].option_counts)

        key = storage_key("scan-pages", scan.school_id, scan.id, f"page-{index:03d}.png")
        _store_page_image(storage, key, image)

        _persist_page(
            db,
            scan=scan,
            page_index=index,
            image_key=key,
            result=result,
            sheet=sheet,
            printed_pages=printed_pages,
            page_in_copy=page_in_copy,
        )
        registered += 1 if result.registered else 0
        identified += 1 if result.uid else 0

        if on_progress is not None:
            on_progress(
                (index + 1) / max(1, len(images)),
                f"page {index + 1} of {len(images)}",
            )

    # Every scan lands in review. Even a page the detector is sure about is the
    # teacher's to confirm — nothing reaches the mastery model unsigned.
    scan.status = ScanStatus.NEEDS_REVIEW
    db.commit()

    log.info(
        "scan.processed",
        scan_id=str(scan_id),
        pages=len(images),
        registered=registered,
        identified=identified,
    )
    return {"pages": len(images), "registered": registered, "identified": identified}


def _page_within_copy(scan_page_index: int, *, images_seen: int, pages: list[Any]) -> int:
    """Which page of that student's copy this scanned sheet is.

    A copy longer than one page arrives as consecutive scans of the same UID, so
    the position within the copy is not the position within the upload. Single-
    page copies — the common case — make this zero.
    """
    if len(pages) <= 1:
        return 0
    return scan_page_index % len(pages)


def _content_type(scan: Scan) -> str:
    name = (scan.original_filename or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    return "image/*"


def _store_page_image(storage: Storage, key: str, image: np.ndarray) -> None:
    import cv2

    ok, buf = cv2.imencode(".png", image)
    if ok:
        storage.put_bytes(key, buf.tobytes(), "image/png")
