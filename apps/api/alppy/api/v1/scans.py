"""Scan upload, review and confirmation.

The upload handler stores bytes and queues a job — it never runs the detector.
Everything a teacher does afterwards is a correction with their name on it, and
confirmation is the single point where readings become graded attempts.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from alppy.api.deps import (
    AiRateLimit,
    DbDep,
    ScopeDep,
    SettingsDep,
    StorageDep,
    TeacherDep,
    check_upload_count,
    read_upload,
    start_job,
)
from alppy.schemas import (
    DetectionCorrection,
    DetectionListOut,
    DetectionOut,
    ScanConfirmResponse,
    ScanOut,
    ScanPageAssign,
    ScanPageDiscard,
    ScanPageOut,
    ScanUnvalidateResponse,
    StudentOut,
)
from alppy.services import detection_out, scan_out, scan_page_out, student_out
from alppy.services import scan_service as svc

router = APIRouter(tags=["scans"])


@router.get("/scans", response_model=list[ScanOut])
def list_scans(
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
    sheet_id: Annotated[uuid.UUID | None, Query()] = None,
    school_year_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ScanOut]:
    """The piles this teacher may see, newest first.

    ``school_year_id`` narrows to one year, through the sheet each pile was
    printed from and the class that sheet was for (audit 02, C3).
    """
    return [
        scan_out(s, storage=storage)
        for s in svc.list_scans(
            db, scope, sheet_id=sheet_id, school_year_id=school_year_id
        )
    ]


# Rate limited even though the handler only stores bytes: PROCESS_SCAN chains
# GRADE_OPEN_ANSWERS, which is one provider call per open answer per copy. One
# unthrottled POST of a 28-copy pile with 6 written items is ~168 calls.
@router.post(
    "/scans",
    response_model=ScanOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AiRateLimit],
)
async def upload_scan(
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    files: Annotated[list[UploadFile], File()],
    sheet_id: Annotated[uuid.UUID, Form()],
) -> ScanOut:
    """Accept a PDF, or a pile of phone photos, and return immediately.

    ``files`` is a list because photographing a class set gives one file per
    copy: 28 photos are ONE pile to review, not 28 scans. Their pages
    concatenate in the order they were selected.

    ``sheet_id`` is required. Without it the pipeline has no answer key, no
    per-copy pagination and no class to check the UIDs against, so it can read
    the marks and then grade exactly nothing — which it used to do while
    reporting success. Which sheet these are copies of is something only the
    teacher knows; asking is the whole cost of never silently discarding a
    class's work.

    Registration, UID reading and bubble detection run in the worker; the
    response is the scan row, whose status the client polls.
    """
    # Before the first read: every payload is bytes held for the life of the
    # request, so the count is what bounds the memory, not the per-file cap.
    check_upload_count(files, settings)
    payloads = [await read_upload(f, settings) for f in files]
    scan, job = svc.create_scan(db, scope.school_id, teacher.id, storage, payloads, sheet_id=sheet_id)
    db.commit()
    start_job(db, job)
    db.refresh(scan)
    return scan_out(scan, storage=storage, job_id=job.id)


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(
    scan_id: uuid.UUID, scope: ScopeDep, db: DbDep, storage: StorageDep
) -> ScanOut:
    return scan_out(svc.get_scan(db, scope, scan_id), storage=storage)


@router.get("/scans/{scan_id}/detections", response_model=DetectionListOut)
def list_detections(
    scan_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> DetectionListOut:
    """One page of the readings from a pile.

    Paged because a pile is one page per pupil per sheet page and each page
    carries one detection per item: twenty-eight copies of a twelve-item sheet
    is 336 rows, each with its fill ratios, its bubble boxes and a presigned
    crop URL — re-read on every correction the teacher makes.

    The default of 200 is deliberately larger than the other collections': the
    review screen wants a whole pile at once where it can, and the cap is what
    stops a very large one from arriving in a single response.
    """
    svc.get_scan(db, scope, scan_id)
    rows, total = svc.list_detections_page(
        db, scope.school_id, scan_id, offset=offset, limit=limit
    )
    return DetectionListOut(
        items=[detection_out(d, storage=storage) for d in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/scans/{scan_id}/detections/{detection_id}", response_model=DetectionOut)
def correct_detection(
    scan_id: uuid.UUID,
    detection_id: uuid.UUID,
    payload: DetectionCorrection,
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> DetectionOut:
    """A teacher overriding the machine, always recorded.

    Refused once the pile is confirmed: the grades were computed from the
    readings as they stood then. Reopen first — that withdraws them.
    """
    svc.get_scan(db, scope, scan_id)
    detection = svc.correct_detection(
        db, scope.school_id, teacher.id, scan_id, detection_id, payload
    )
    db.commit()
    db.refresh(detection)
    return detection_out(detection, storage=storage)


@router.post(
    "/scans/{scan_id}/detections/{detection_id}/revert", response_model=DetectionOut
)
def revert_detection(
    scan_id: uuid.UUID,
    detection_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> DetectionOut:
    """Undo a correction, restoring exactly what the machine read.

    Refused on a reading that was never corrected, and on a confirmed pile.
    """
    detection = svc.revert_detection(db, scope, scan_id, detection_id)
    db.commit()
    db.refresh(detection)
    return detection_out(detection, storage=storage)


@router.post("/scans/{scan_id}/reopen", response_model=ScanUnvalidateResponse)
def reopen_scan(scan_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> ScanUnvalidateResponse:
    """Take a confirmed pile back into review.

    Withdraws the grades this confirmation wrote, puts back any that an older
    still-confirmed pile still accounts for, and recomputes mastery. An item
    with no older reading simply has no grade again — not a zero.
    """
    result = svc.unvalidate_scan(db, scope, scan_id)
    db.commit()
    return result


@router.get("/scans/{scan_id}/students", response_model=list[StudentOut])
def assignable_students(
    scan_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    on: Annotated[date | None, Query()] = None,
) -> list[StudentOut]:
    """Who a page of this scan may be assigned to.

    The class the sheet was printed for, and nobody else: assigning a page to a
    student from another class files one child's answers under another's name.

    The roster is read as of the day the SHEET was made, which is usually the
    right guess. ``on`` overrides it for the case the guess gets wrong: a sheet
    composed in September and sat in November, by a group that changed in
    between (audit 02, C3).
    """
    return [student_out(s) for s in svc.assignable_students(db, scope, scan_id, on=on)]


@router.post("/scans/{scan_id}/pages/{page_id}/discard", response_model=ScanPageOut)
def discard_page(
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: ScanPageDiscard,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> ScanPageOut:
    """Take a page out of the pile, or put it back.

    A cover sheet or a lens-cap frame belongs to nobody, and without this the
    only way past it was to attribute it to a real child.
    """
    page = svc.set_page_discarded(
        db, scope, scan_id, page_id, discarded=payload.discarded
    )
    db.commit()
    db.refresh(page)
    return scan_page_out(page, storage=storage)


@router.patch("/scans/{scan_id}/pages/{page_id}", response_model=ScanPageOut)
def assign_page(
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: ScanPageAssign,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> ScanPageOut:
    """Manual fallback when the printed UID grid could not be read."""
    svc.get_scan(db, scope, scan_id)
    page = svc.assign_page_student(
        db, scope, scan_id, page_id, payload.student_id, storage=storage
    )
    # Re-reading the page may have cut written answers no job was chained
    # for; they get their grader now.
    follow_up = svc.queue_grading_if_pending(db, scope, scan_id)
    db.commit()
    if follow_up is not None:
        start_job(db, follow_up)
    db.refresh(page)
    return scan_page_out(page, storage=storage)


@router.post("/scans/{scan_id}/confirm", response_model=ScanConfirmResponse)
def confirm_scan(
    scan_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> ScanConfirmResponse:
    """Grade the confirmed readings and recompute the affected mastery cells."""
    result = svc.confirm_scan(db, scope, scan_id)
    db.commit()
    return result
