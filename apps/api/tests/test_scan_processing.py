"""The bridge from "the detector read a page" to "rows a teacher can review".

This module used to have no tests at all, and every defect the F2 review found
lived in it. Each test here is one of those defects, written so that it fails
against the code as it was.

Everything drives the real ``process_scan`` and ``confirm_scan`` over real
synthetic pages — no hand-built ``Detection`` rows. That seam is the point.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

import cv2
import numpy as np
import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise

from alppy.api.errors import ApiError
from alppy.models import Attempt, Detection, Scan, ScanPage, Sheet, SheetInstance, SheetItem
from alppy.models.enums import DetectionOutcome, ExerciseType, ScanStatus, SheetTarget
from alppy.scan.synthetic import render_page
from alppy.schemas import DetectionCorrection
from alppy.services import scan_processing, scan_service
from alppy.sheets.pagination import paginate
from alppy.sheets.render import build_sheet_data
from alppy.storage import LocalStorage

Marks = list[int | None]


# --------------------------------------------------------------------------
# Scaffolding
# --------------------------------------------------------------------------
def _sheet(
    db: Session,
    tenant: Tenant,
    *,
    answers: list[int],
    kinds: list[ExerciseType] | None = None,
    plans: dict[str, list[int]] | None = None,
) -> tuple[Sheet, list]:
    """A sheet whose items have *different* correct answers.

    Different on purpose: the demo seed answers every MCQ with option 0, so a
    pipeline that always guessed "A" would score full marks against it and any
    accuracy assertion built on it would prove nothing.

    ``plans`` maps a student UID to the positions of ``answers`` that student's
    copy prints — the shape ``create_adaptive_sheet`` produces, where
    ``sheet.items`` is the union over the class and each instance carries its
    own ordered subset.
    """
    kinds = kinds or [ExerciseType.MCQ] * len(answers)
    exercises = [
        make_exercise(
            db,
            tenant,
            statement=f"Question {i}",
            kind=kind,
            answer_index=None if kind is ExerciseType.OPEN else answer,
            answer_bool=(answer == 0) if kind is ExerciseType.TRUE_FALSE else None,
        )
        for i, (answer, kind) in enumerate(zip(answers, kinds, strict=True))
    ]
    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        class_id=tenant.school_class.id,
        subject_id=tenant.subject.id,
        created_by_id=tenant.teacher.id,
        title="Fractions",
        target=SheetTarget.CLASS,
        language="fr",
        layout_version="v1",
    )
    db.add(sheet)
    db.flush()
    for position, exercise in enumerate(exercises, start=1):
        db.add(
            SheetItem(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                sheet_id=sheet.id,
                exercise_id=exercise.id,
                position=position,
            )
        )
    for student in tenant.students:
        chosen = (plans or {}).get(student.uid, list(range(len(exercises))))
        db.add(
            SheetInstance(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                sheet_id=sheet.id,
                student_id=student.id,
                student_uid=student.uid,
                item_plan=[
                    {"exercise_id": str(exercises[i].id), "variant_id": None, "position": n}
                    for n, i in enumerate(chosen, start=1)
                ],
            )
        )
    db.flush()
    db.commit()
    db.refresh(sheet)
    return sheet, exercises


def _run(
    db: Session,
    storage: LocalStorage,
    tenant: Tenant,
    sheet: Sheet | None,
    images: list[np.ndarray],
    monkeypatch: pytest.MonkeyPatch,
) -> Scan:
    """Push a pile of page images through the real worker path."""
    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        sheet_id=sheet.id if sheet else None,
        uploaded_by_id=tenant.teacher.id,
        original_filename="pile.pdf",
        storage_key="pile.pdf",
        storage_keys=["pile.pdf"],
        layout_version=sheet.layout_version if sheet else None,
        status=ScanStatus.UPLOADED,
    )
    db.add(scan)
    db.flush()
    storage.put_bytes("pile.pdf", b"%PDF-1.7", "application/pdf")
    db.commit()
    monkeypatch.setattr(scan_processing, "_decode_pages", lambda *a, **k: list(images))
    scan_processing.process_scan(db, storage, scan_id=scan.id)
    return scan


def _copy_pages(db: Session, sheet: Sheet, uid: str) -> list:
    data = build_sheet_data(db, sheet)
    copy = next(c for c in data.copies if c.uid == uid)
    return list(paginate(list(copy.items)))


def _render_copy(db: Session, sheet: Sheet, uid: str, *, all_correct: bool = True) -> list:
    """Every physical page of one student's copy, filled from its own key."""
    images = []
    for page in _copy_pages(db, sheet, uid):
        marks: Marks = [
            (p.item.answer_index if all_correct else None) if p.item.is_gradeable else None
            for p in page.items
        ]
        images.append(render_page(uid, page.option_counts, marks, pencil=0.95).image)
    return images


def _attempts(db: Session, scan: Scan) -> list[Attempt]:
    ids = [
        d.id
        for d in db.query(Detection)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .filter(ScanPage.scan_id == scan.id)
        .all()
    ]
    return db.query(Attempt).filter(Attempt.detection_id.in_(ids)).all()


# --------------------------------------------------------------------------
# P0-3 · a differentiated copy is graded against the questions IT printed
# --------------------------------------------------------------------------
def test_a_differentiated_copy_is_graded_against_its_own_items(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``sheet.items`` is the union over the class; each copy prints a subset.

    Pairing a detection by its position in the union graded this student's
    first answer against the class's first question — a child who answered
    everything on their own paper correctly scored zero, at full confidence,
    against an exercise that was never printed for them.
    """
    student = tenant.students[0]
    # Union answers A, B, C; this student's copy prints only #3 then #1.
    sheet, exercises = _sheet(
        db, tenant, answers=[0, 1, 2], plans={student.uid: [2, 0]}
    )

    images = _render_copy(db, sheet, student.uid)
    scan = _run(db, storage, tenant, sheet, images, monkeypatch)

    detections = sorted(
        db.query(Detection).join(ScanPage).filter(ScanPage.scan_id == scan.id).all(),
        key=lambda d: d.item_index,
    )
    assert [d.exercise_id for d in detections] == [exercises[2].id, exercises[0].id]
    # The printed number is the one on the paper, not the index in the union.
    assert [d.printed_number for d in detections] == [1, 2]

    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    graded = {a.exercise_id: a.correct for a in _attempts(db, scan)}
    assert graded == {exercises[2].id: True, exercises[0].id: True}


# --------------------------------------------------------------------------
# P0-4 · one unreadable page must cost that page and nothing else
# --------------------------------------------------------------------------
def test_an_unreadable_page_does_not_shift_the_copies_behind_it(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which page of whose copy a scan is comes from the decoded UID.

    It used to come from the position in the upload, so a lens-cap frame at the
    front of the pile shifted every copy behind it by one page and graded them
    against the wrong questions — 8 of 10 attempts wrong for students who had
    answered everything correctly.
    """
    sheet, _ = _sheet(db, tenant, answers=[0, 1, 2, 3, 0])
    two = tenant.students[:2]
    assert len(_copy_pages(db, sheet, two[0].uid)) > 1, "need a multi-page copy"

    images: list[np.ndarray] = []
    for student in two:
        images.extend(_render_copy(db, sheet, student.uid))
    junk = np.full_like(images[0], 255)

    scan = _run(db, storage, tenant, sheet, [junk, *images], monkeypatch)

    # The junk page belongs to nobody and must not consume anyone's slot.
    pages = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).all()
    assert [p.page_in_copy for p in pages if p.registered] == [
        p.page_in_copy for p in pages if p.page_in_copy is not None
    ]

    scan_service.set_page_discarded(
        db,
        tenant.scope,
        scan.id,
        next(p.id for p in pages if not p.registered),
        discarded=True,
    )
    db.commit()
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    attempts = _attempts(db, scan)
    assert attempts, "the good copies must still grade"
    assert all(a.correct for a in attempts), "everyone answered everything correctly"


# --------------------------------------------------------------------------
# P1-7 · a junk page must not hold the other copies hostage
# --------------------------------------------------------------------------
def test_a_discarded_page_does_not_block_confirmation(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = _render_copy(db, sheet, tenant.students[0].uid)
    junk = np.full_like(images[0], 255)
    scan = _run(db, storage, tenant, sheet, [*images, junk], monkeypatch)

    with pytest.raises(ApiError, match="assigned to a student, or discarded"):
        scan_service.confirm_scan(db, tenant.scope, scan.id)

    junk_page = next(
        p for p in db.query(ScanPage).filter(ScanPage.scan_id == scan.id) if not p.registered
    )
    scan_service.set_page_discarded(
        db, tenant.scope, scan.id, junk_page.id, discarded=True
    )
    db.commit()

    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    assert result.attempts_created == 2
    assert db.get(Scan, scan.id).status is ScanStatus.CONFIRMED


# --------------------------------------------------------------------------
# P1-5 · a page from another class is flagged, not silently absorbed
# --------------------------------------------------------------------------
def test_a_page_from_another_class_is_flagged_and_not_graded(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alppy.models import Class, Student

    other = Class(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        school_year_id=tenant.school_class.school_year_id,
        teacher_id=tenant.teacher.id,
        code="9A",
        label="Autre",
    )
    db.add(other)
    db.flush()
    db.add(
        Student(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            class_id=other.id,
            school_year_id=tenant.school_class.school_year_id,
            uid="9A_04",
            number=4,
            first_name="Tim",
            last_name="Frei",
        )
    )
    db.flush()

    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = [
        *_render_copy(db, sheet, tenant.students[0].uid),
        render_page("9A_04", [4, 4], [0, 1], pencil=0.95).image,
    ]
    scan = _run(db, storage, tenant, sheet, images, monkeypatch)

    foreign = db.query(ScanPage).filter(ScanPage.detected_uid == "9A_04").one()
    assert foreign.wrong_class is True
    # No phantom rows: reading someone else's paper against this grid produced
    # a screenful of low-confidence items about a page that is not ours.
    assert foreign.detections == []

    # And it does not block the rest of the pile.
    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    assert result.attempts_created == 2


# --------------------------------------------------------------------------
# P1-8 · re-scanning a pile corrects the record instead of doubling it
# --------------------------------------------------------------------------
def test_rescanning_supersedes_instead_of_duplicating(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mastery is a weighted mean over attempts, so a duplicated sheet does not
    move the score much but silently doubles one lesson's weight."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid

    first = _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    scan_service.confirm_scan(db, tenant.scope, first.id)
    db.commit()
    assert db.query(Attempt).count() == 2
    assert all(a.correct for a in db.query(Attempt).all())

    # The same pile again — this time every answer wrong.
    wrong = _render_copy(db, sheet, uid, all_correct=False)
    second = _run(db, storage, tenant, sheet, wrong, monkeypatch)
    result = scan_service.confirm_scan(db, tenant.scope, second.id)
    db.commit()

    assert result.attempts_created == 0
    assert result.attempts_superseded == 2
    assert db.query(Attempt).count() == 2, "one row per student x exercise x sheet"
    # The re-scan corrected the record rather than accumulating beside it.
    assert not any(a.correct for a in db.query(Attempt).all())


def test_confirming_the_same_scan_twice_is_still_a_conflict(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    scan = _run(
        db, storage, tenant, sheet, _render_copy(db, sheet, tenant.students[0].uid), monkeypatch
    )
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    with pytest.raises(ApiError, match="already confirmed"):
        scan_service.confirm_scan(db, tenant.scope, scan.id)


# --------------------------------------------------------------------------
# P1-3 · the machine's reading survives the teacher's override
# --------------------------------------------------------------------------
def test_a_correction_keeps_the_machine_reading_beside_it(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    scan = _run(
        db, storage, tenant, sheet, _render_copy(db, sheet, tenant.students[0].uid), monkeypatch
    )
    detection = (
        db.query(Detection).join(ScanPage).filter(ScanPage.scan_id == scan.id).first()
    )
    assert detection is not None
    machine = (detection.detected_index, detection.outcome, detection.confidence)
    assert detection.machine_index == machine[0]

    scan_service.correct_detection(
        db,
        tenant.school.id,
        tenant.teacher.id,
        scan.id,
        detection.id,
        DetectionCorrection(detected_index=3),
    )
    db.commit()
    db.refresh(detection)

    assert detection.outcome is DetectionOutcome.CORRECTED
    assert detection.detected_index == 3
    assert detection.corrected_by_id == tenant.teacher.id
    # ...and what it disagreed with is still there.
    assert (
        detection.machine_index,
        detection.machine_outcome,
        detection.machine_confidence,
    ) == machine


def test_a_true_false_item_cannot_be_corrected_to_a_bubble_it_never_printed(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(
        db, tenant, answers=[0, 0], kinds=[ExerciseType.TRUE_FALSE, ExerciseType.MCQ]
    )
    scan = _run(
        db, storage, tenant, sheet, _render_copy(db, sheet, tenant.students[0].uid), monkeypatch
    )
    tf = (
        db.query(Detection)
        .join(ScanPage)
        .filter(ScanPage.scan_id == scan.id, Detection.item_index == 0)
        .one()
    )
    with pytest.raises(ApiError, match="2 options"):
        scan_service.correct_detection(
            db,
            tenant.school.id,
            tenant.teacher.id,
            scan.id,
            tf.id,
            DetectionCorrection(detected_index=3),
        )


# --------------------------------------------------------------------------
# P1-11 · items that produced no attempt are counted, not dropped in silence
# --------------------------------------------------------------------------
def test_ungradeable_items_are_reported_rather_than_vanishing(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alppy.scan.detector import PX_PER_MM
    from alppy.sheets import layout as L

    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    images = _render_copy(db, sheet, uid)
    # Fill a second bubble on item 0: the teacher's question, not the machine's.
    cx, cy = L.bubble_centre_mm(0, 2)
    cv2.circle(
        images[0],
        (int(cx * PX_PER_MM), int(cy * PX_PER_MM)),
        int(L.BUBBLE_D_MM / 2 * PX_PER_MM * 0.75),
        0,
        -1,
    )
    scan = _run(db, storage, tenant, sheet, images, monkeypatch)

    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    assert result.items_skipped == 1
    assert result.attempts_created == 1


def test_a_heic_photo_from_an_iphone_is_read(
    db: Session, storage: LocalStorage, tenant: Tenant
) -> None:
    """iOS photographs in HEIC by default, and neither OpenCV nor Pillow reads
    it unaided — so the format was rejected at the content-type gate on a
    workflow (`docs/plan.md` §9) that is a phone camera pointed at paper.

    This goes through the real decoder, not the allowlist: accepting the
    content type without a decode path only moves the failure downstream.
    """
    import io

    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image as PilImage

    # Registering teaches Pillow both ends; the test needs the encoder to make
    # a file, the pipeline needs the decoder to read one.
    pillow_heif.register_heif_opener()

    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    student = tenant.students[0]
    page = _render_copy(db, sheet, student.uid)[0]

    buffer = io.BytesIO()
    PilImage.fromarray(page).convert("RGB").save(buffer, format="HEIF", quality=90)
    heic = buffer.getvalue()
    assert heic[4:8] == b"ftyp", "not an ISO-BMFF file"

    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        sheet_id=sheet.id,
        uploaded_by_id=tenant.teacher.id,
        original_filename="IMG_0042.heic",
        storage_key="copy.heic",
        storage_keys=["copy.heic"],
        layout_version=sheet.layout_version,
        status=ScanStatus.UPLOADED,
    )
    db.add(scan)
    db.flush()
    storage.put_bytes("copy.heic", heic, "image/heic")
    db.commit()

    scan_processing.process_scan(db, storage, scan_id=scan.id)

    scan_page = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).one()
    assert scan_page.registered, "the HEIC never reached the detector"
    assert scan_page.detected_uid == student.uid

    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    assert result.attempts_created == 2
    assert all(a.correct for a in _attempts(db, scan))


# --------------------------------------------------------------------------
# P1-12 · a corrupt upload fails loudly
# --------------------------------------------------------------------------
def test_a_corrupt_upload_raises_so_the_job_records_a_failure(
    db: Session, storage: LocalStorage, tenant: Tenant
) -> None:
    """It used to return a result dict, so the job reported success at progress
    1.0 while the scan sat in FAILED — a green tick and an empty review page."""
    sheet, _ = _sheet(db, tenant, answers=[0])
    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        sheet_id=sheet.id,
        uploaded_by_id=tenant.teacher.id,
        original_filename="broken.pdf",
        storage_key="broken.pdf",
        storage_keys=["broken.pdf"],
        status=ScanStatus.UPLOADED,
    )
    db.add(scan)
    db.flush()
    storage.put_bytes("broken.pdf", b"%PDF-1.7\n" + b"\x00" * 512, "application/pdf")
    db.commit()

    with pytest.raises(scan_processing.ScanDecodeError):
        scan_processing.process_scan(db, storage, scan_id=scan.id)

    db.expire_all()
    failed = db.get(Scan, scan.id)
    assert failed is not None
    assert failed.status is ScanStatus.FAILED
    # A message a teacher can act on, not a library's exception text.
    assert "readable PDF" in (failed.error or "")


# --------------------------------------------------------------------------
# P1-2 · manual assignment offers this sheet's class, and nobody else
# --------------------------------------------------------------------------
def test_manual_assignment_is_limited_to_the_sheets_own_class(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    from alppy.models import Class, Student

    other = Class(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        school_year_id=tenant.school_class.school_year_id,
        teacher_id=tenant.teacher.id,
        code="9A",
        label="Autre",
    )
    db.add(other)
    db.flush()
    outsider = Student(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        class_id=other.id,
        school_year_id=tenant.school_class.school_year_id,
        uid="9A_04",
        number=4,
        first_name="Tim",
        last_name="Frei",
    )
    db.add(outsider)
    db.flush()

    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = _render_copy(db, sheet, tenant.students[0].uid)
    blank = np.full_like(images[0], 255)
    scan = _run(db, storage, tenant, sheet, [*images, blank], monkeypatch)

    offered = {s.uid for s in scan_service.assignable_students(db, tenant.scope, scan.id)}
    assert offered == {s.uid for s in tenant.students}
    assert "9A_04" not in offered

    page = next(
        p for p in db.query(ScanPage).filter(ScanPage.scan_id == scan.id) if not p.registered
    )
    with pytest.raises(ApiError, match="not in the class"):
        scan_service.assign_page_student(
            db, tenant.scope, scan.id, page.id, outsider.id
        )


def test_assigning_a_page_by_hand_makes_it_gradeable(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming the student has to re-read the page against their copy.

    Until the copy is known the page is read against the full default grid and
    every reading is left unpaired, because "item 3" means nothing without a
    copy. Assigning used to name the student and stop there, so the manual
    fallback produced a screen full of detections that graded nothing — the
    exact failure it exists to prevent.
    """
    from alppy.scan.detector import PX_PER_MM
    from alppy.sheets import layout as L

    sheet, exercises = _sheet(db, tenant, answers=[0, 1])
    student = tenant.students[0]
    images = _render_copy(db, sheet, student.uid)
    # Smudge the printed UID grid: coffee, a fold, a bad photocopy. The page
    # still registers; its code does not decode.
    ox, oy = L.UID_GRID_ORIGIN_MM
    w = L.UID_GRID_CELLS * (L.UID_GRID_CELL_MM + L.UID_GRID_GAP_MM)
    h = L.UID_GRID_ROWS * (L.UID_GRID_CELL_MM + L.UID_GRID_GAP_MM)
    cv2.rectangle(
        images[0],
        (int((ox - 1) * PX_PER_MM), int((oy - 1) * PX_PER_MM)),
        (int((ox + w) * PX_PER_MM), int((oy + h) * PX_PER_MM)),
        255,
        -1,
    )

    scan = _run(db, storage, tenant, sheet, images, monkeypatch)
    page = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).one()
    assert page.detected_uid is None
    assert page.student_id is None
    assert all(d.exercise_id is None for d in page.detections)

    scan_service.assign_page_student(
        db, tenant.scope, scan.id, page.id, student.id, storage=storage
    )
    db.commit()
    db.refresh(page)

    # Read again against the copy it turned out to be.
    assert page.student_id == student.id
    assert [d.exercise_id for d in sorted(page.detections, key=lambda d: d.item_index)] == [
        exercises[0].id,
        exercises[1].id,
    ]

    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()
    assert result.attempts_created == 2
    assert all(a.correct for a in _attempts(db, scan))


# --------------------------------------------------------------------------
# P1-1 · the stored review image is the one the coordinates describe
# --------------------------------------------------------------------------
def test_the_stored_page_image_is_the_registered_one(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The overlay draws boxes at the coordinates the detector sampled, and
    those only line up with the deskewed page."""
    from alppy.scan.detector import CANONICAL_H, CANONICAL_W
    from alppy.scan.synthetic import rotate

    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = [rotate(img, 3.0) for img in _render_copy(db, sheet, tenant.students[0].uid)]
    scan = _run(db, storage, tenant, sheet, images, monkeypatch)

    page = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).first()
    assert page is not None and page.registered
    stored = cv2.imdecode(
        np.frombuffer(storage.get_bytes(page.image_key), dtype=np.uint8),
        cv2.IMREAD_GRAYSCALE,
    )
    assert stored.shape == (CANONICAL_H, CANONICAL_W)


# --------------------------------------------------------------------------
# P0-2 · a pile that cannot be matched to its sheet is refused, not "saved"
# --------------------------------------------------------------------------
def test_a_scan_that_can_grade_nothing_is_refused_at_confirm(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = _render_copy(db, sheet, tenant.students[0].uid)
    # A pile with no sheet behind it: every reading is unattached.
    scan = _run(db, storage, tenant, None, images, monkeypatch)

    with pytest.raises(ApiError, match="nothing to grade"):
        scan_service.confirm_scan(db, tenant.scope, scan.id)
    assert db.get(Scan, scan.id).status is not ScanStatus.CONFIRMED


# --------------------------------------------------------------------------
# P1-4 · a page printed under another layout is refused, not misread
# --------------------------------------------------------------------------
def test_a_page_printed_under_another_layout_is_not_read(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    images = _render_copy(db, sheet, tenant.students[0].uid)
    sheet.layout_version = "v2"
    db.commit()

    scan = _run(db, storage, tenant, sheet, images, monkeypatch)
    pages = db.query(ScanPage).filter(ScanPage.scan_id == scan.id).all()
    assert all(not p.registered for p in pages)
    assert all("layout v2" in (p.registration_meta or {}).get("error", "") for p in pages)
    assert db.query(Detection).join(ScanPage).filter(ScanPage.scan_id == scan.id).count() == 0


# --------------------------------------------------------------------------
# The happy path, end to end, on a multi-page copy
# --------------------------------------------------------------------------
@pytest.mark.parametrize("degrade", ["none", "phone_photo", "copier"])
def test_a_whole_class_set_grades_correctly(
    db: Session,
    storage: LocalStorage,
    tenant: Tenant,
    monkeypatch: pytest.MonkeyPatch,
    degrade: str,
) -> None:
    from alppy.scan import synthetic

    fn: Callable[[np.ndarray], np.ndarray] = {
        "none": lambda i: i,
        "phone_photo": synthetic.phone_photo,
        "copier": synthetic.copier,
    }[degrade]

    sheet, exercises = _sheet(
        db,
        tenant,
        answers=[0, 1, 2, 0, 1],
        kinds=[
            ExerciseType.MCQ,
            ExerciseType.MCQ,
            ExerciseType.MCQ,
            ExerciseType.TRUE_FALSE,
            ExerciseType.OPEN,
        ],
    )
    images: list[np.ndarray] = []
    for student in tenant.students:
        images.extend(fn(img) for img in _render_copy(db, sheet, student.uid))

    scan = _run(db, storage, tenant, sheet, images, monkeypatch)
    result = scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    attempts = _attempts(db, scan)
    # Four gradeable items per student; the free-text one is never scored.
    assert result.attempts_created == 4 * len(tenant.students)
    assert all(a.correct for a in attempts)
    assert not any(a.exercise_id == exercises[4].id for a in attempts)
