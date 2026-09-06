"""Scan upload, review and confirmation.

The upload handler stores bytes and queues a job — it never runs the detector.
Everything a teacher does afterwards is a correction with their name on it, and
confirmation is the single point where readings become graded attempts.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from alppy.api.deps import (
    DbDep,
    SettingsDep,
    StorageDep,
    TeacherDep,
    TenantDep,
    read_upload,
    start_job,
)
from alppy.schemas import (
    DetectionCorrection,
    DetectionOut,
    ScanConfirmResponse,
    ScanOut,
    ScanPageAssign,
    ScanPageOut,
)
from alppy.services import detection_out, scan_out, scan_page_out
from alppy.services import scan_service as svc

router = APIRouter(tags=["scans"])


@router.get("/scans", response_model=list[ScanOut])
def list_scans(
    school_id: TenantDep,
    db: DbDep,
    storage: StorageDep,
    sheet_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ScanOut]:
    return [
        scan_out(s, storage=storage) for s in svc.list_scans(db, school_id, sheet_id=sheet_id)
    ]


@router.post("/scans", response_model=ScanOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_scan(
    teacher: TeacherDep,
    school_id: TenantDep,
    db: DbDep,
    settings: SettingsDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    sheet_id: Annotated[uuid.UUID | None, Form()] = None,
) -> ScanOut:
    """Accept a PDF or a phone photo and return immediately.

    Registration, UID reading and bubble detection run in the worker; the
    response is the scan row, whose status the client polls.
    """
    payload = await read_upload(file, settings)
    scan, job = svc.create_scan(db, school_id, teacher.id, storage, payload, sheet_id=sheet_id)
    db.commit()
    start_job(db, job)
    db.refresh(scan)
    return scan_out(scan, storage=storage)


@router.get("/scans/{scan_id}", response_model=ScanOut)
def get_scan(
    scan_id: uuid.UUID, school_id: TenantDep, db: DbDep, storage: StorageDep
) -> ScanOut:
    return scan_out(svc.get_scan(db, school_id, scan_id), storage=storage)


@router.get("/scans/{scan_id}/detections", response_model=list[DetectionOut])
def list_detections(
    scan_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> list[DetectionOut]:
    svc.get_scan(db, school_id, scan_id)
    return [detection_out(d) for d in svc.list_detections(db, school_id, scan_id)]


@router.patch("/scans/{scan_id}/detections/{detection_id}", response_model=DetectionOut)
def correct_detection(
    scan_id: uuid.UUID,
    detection_id: uuid.UUID,
    payload: DetectionCorrection,
    teacher: TeacherDep,
    school_id: TenantDep,
    db: DbDep,
) -> DetectionOut:
    """A teacher overriding the machine. Always allowed, always recorded."""
    svc.get_scan(db, school_id, scan_id)
    detection = svc.correct_detection(
        db, school_id, teacher.id, scan_id, detection_id, payload
    )
    db.commit()
    db.refresh(detection)
    return detection_out(detection)


@router.patch("/scans/{scan_id}/pages/{page_id}", response_model=ScanPageOut)
def assign_page(
    scan_id: uuid.UUID,
    page_id: uuid.UUID,
    payload: ScanPageAssign,
    school_id: TenantDep,
    db: DbDep,
    storage: StorageDep,
) -> ScanPageOut:
    """Manual fallback when the printed UID grid could not be read."""
    svc.get_scan(db, school_id, scan_id)
    page = svc.assign_page_student(db, school_id, scan_id, page_id, payload.student_id)
    db.commit()
    db.refresh(page)
    return scan_page_out(page, storage=storage)


@router.post("/scans/{scan_id}/confirm", response_model=ScanConfirmResponse)
def confirm_scan(
    scan_id: uuid.UUID, school_id: TenantDep, db: DbDep
) -> ScanConfirmResponse:
    """Grade the confirmed readings and recompute the affected mastery cells."""
    result = svc.confirm_scan(db, school_id, scan_id)
    db.commit()
    return result
