"""Scan upload validation, teacher corrections, and confirm -> attempts -> bands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import PDF_BYTES, PNG_BYTES, Tenant, login, make_exercise

from alppy.models import Attempt, Detection, Scan, ScanPage, Sheet, SheetInstance
from alppy.models.enums import DetectionOutcome, ExerciseType, ScanStatus

CORRECT_INDEX = 1


# --------------------------------------------------------------------------
# Upload validation
# --------------------------------------------------------------------------
@pytest.fixture
def sheet_id(client: TestClient, tenant: Tenant, db: Session) -> str:
    """A sheet to attach an upload to.

    ``sheet_id`` is required on POST /scans: a pile that is not linked to the
    sheet it was printed from has no answer key, no per-copy pagination and no
    class to check its UIDs against, so it can read every mark and grade
    nothing.
    """
    login(client, tenant.teacher.email)
    exercise = make_exercise(db, tenant, statement="Une question", answer_index=1)
    body = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Copies",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    ).json()
    return str(body["id"])


def test_upload_without_a_sheet_is_refused(client: TestClient, tenant: Tenant) -> None:
    """The failure this prevents is silent: marks read, nothing graded, and the
    teacher told their results were saved."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans", files={"files": ("copies.pdf", PDF_BYTES, "application/pdf")}
    )
    assert response.status_code == 422
    assert any(
        e["loc"][-1] == "sheet_id" for e in response.json()["error"]["details"]["errors"]
    )


def test_upload_accepts_a_pdf_and_returns_without_detecting_anything(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("copies.pdf", PDF_BYTES, "application/pdf")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["pages"] == []  # detection happens in the worker, never here

    jobs = client.get("/api/v1/jobs?kind=process_scan").json()
    assert [j["status"] for j in jobs] == ["queued"]
    assert jobs[0]["message"]


def test_upload_accepts_a_phone_photo(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("IMG_0042.png", PNG_BYTES, "image/png")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "uploaded"
    assert body["original_filename"] == "IMG_0042.png"

    scan = db.execute(select(Scan)).scalars().one()
    assert scan.storage_keys == [scan.storage_key]
    assert client.get("/api/v1/jobs?kind=process_scan").json()[0]["status"] == "queued"


def test_a_pile_of_photos_is_one_scan_not_one_each(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """Photographing a class set gives one file per copy. The teacher expects
    one review session, not twenty-eight."""
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files=[
            ("files", ("IMG_0042.png", PNG_BYTES, "image/png")),
            ("files", ("IMG_0043.png", PNG_BYTES, "image/png")),
            ("files", ("IMG_0044.png", PNG_BYTES, "image/png")),
        ],
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202

    scans = db.execute(select(Scan)).scalars().all()
    assert len(scans) == 1
    assert len(scans[0].storage_keys or []) == 3
    assert scans[0].original_filename == "IMG_0042.png, IMG_0043.png, IMG_0044.png"
    # One job too: one pile, one piece of work.
    assert len(client.get("/api/v1/jobs?kind=process_scan").json()) == 1


def test_upload_accepts_a_heic_photo(
    client: TestClient, tenant: Tenant, sheet_id: str
) -> None:
    """The format an iPhone produces by default is not an exotic case."""
    import io

    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image as PilImage

    pillow_heif.register_heif_opener()
    buffer = io.BytesIO()
    PilImage.new("RGB", (64, 64), "white").save(buffer, format="HEIF")

    response = client.post(
        "/api/v1/scans",
        files={"files": ("IMG_0042.heic", buffer.getvalue(), "image/heic")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202


def test_upload_rejects_something_only_claiming_to_be_heic(
    client: TestClient, tenant: Tenant, sheet_id: str
) -> None:
    """The allowlist accepts the type; the magic bytes decide whether it is one."""
    response = client.post(
        "/api/v1/scans",
        files={"files": ("fake.heic", b"not an ISO-BMFF file at all", "image/heic")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 415
    assert "do not look like" in response.json()["error"]["message"]


def test_upload_rejects_a_disallowed_content_type(client: TestClient, tenant: Tenant, sheet_id: str) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("notes.txt", b"hello", "text/plain")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_upload_rejects_a_file_that_is_not_what_it_claims(
    client: TestClient, tenant: Tenant, sheet_id: str
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("evil.pdf", b"MZ\x90\x00 not a pdf", "application/pdf")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 415
    assert "do not look like" in response.json()["error"]["message"]


def test_upload_rejects_an_oversized_file(client: TestClient, tenant: Tenant, sheet_id: str) -> None:
    login(client, tenant.teacher.email)
    oversized = b"%PDF-1.7\n" + b"0" * (2 * 1024 * 1024)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("huge.pdf", oversized, "application/pdf")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_upload_rejects_an_empty_file(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("empty.pdf", b"", "application/pdf")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unprocessable"
    assert "empty" in response.json()["error"]["message"]
    # Nothing was written: a rejected upload leaves no scan and no job behind.
    assert db.execute(select(Scan)).scalars().all() == []
    assert client.get("/api/v1/jobs?kind=process_scan").json() == []


def test_a_hostile_filename_never_becomes_a_storage_path(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/scans",
        files={"files": ("../../../etc/passwd.pdf", PDF_BYTES, "application/pdf")},
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202
    scan = db.execute(select(Scan)).scalars().one()
    assert ".." not in scan.storage_key
    assert scan.storage_key.startswith(f"scans/{tenant.school.id}/{scan.id}/")
    assert scan.storage_key.endswith("/passwd.pdf")


# --------------------------------------------------------------------------
# A whole sheet, scanned back in
# --------------------------------------------------------------------------
def _build_scanned_sheet(client: TestClient, tenant: Tenant, db: Session) -> dict[str, object]:
    """A six-MCQ sheet plus one ambiguous item and one free-text item."""
    mcqs = [
        make_exercise(db, tenant, statement=f"Question {i}", answer_index=CORRECT_INDEX)
        for i in range(6)
    ]
    ambiguous = make_exercise(db, tenant, statement="Deux bulles", answer_index=CORRECT_INDEX)
    open_item = make_exercise(
        db,
        tenant,
        statement="Explique ta demarche",
        kind=ExerciseType.OPEN,
        answer_index=None,
    )
    every = [*mcqs, ambiguous, open_item]

    sheet_body = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions",
            "language": "fr",
            "items": [
                {"exercise_id": str(e.id), "position": i} for i, e in enumerate(every)
            ],
        },
    ).json()

    sheet = db.get(Sheet, uuid.UUID(sheet_body["id"]))
    assert sheet is not None
    student = tenant.students[0]
    instance = db.execute(
        select(SheetInstance)
        .where(SheetInstance.sheet_id == sheet.id)
        .where(SheetInstance.student_id == student.id)
    ).scalar_one()

    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        sheet_id=sheet.id,
        uploaded_by_id=tenant.teacher.id,
        original_filename="copies.pdf",
        storage_key=f"scans/{tenant.school.id}/x/copies.pdf",
        status=ScanStatus.NEEDS_REVIEW,
    )
    page = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=scan.id,
        page_index=0,
        image_key="scans/x/p0.png",
        registered=True,
        detected_uid=student.uid,
        uid_confidence=0.99,
        student_id=student.id,
        sheet_instance_id=instance.id,
    )
    db.add_all([scan, page])
    db.flush()

    items = sorted(sheet.items, key=lambda i: i.position)
    detections: list[Detection] = []
    for index, item in enumerate(items):
        if index < 5:
            outcome, detected = DetectionOutcome.DETECTED, CORRECT_INDEX
        elif index == 5:
            outcome, detected = DetectionOutcome.LOW_CONFIDENCE, 0  # wrong, to be corrected
        elif index == 6:
            outcome, detected = DetectionOutcome.MULTIPLE, None  # never guessed
        else:
            outcome, detected = DetectionOutcome.NOT_GRADEABLE, None  # free text
        detection = Detection(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            scan_page_id=page.id,
            sheet_item_id=item.id,
            item_index=index,
            detected_index=detected,
            confidence=0.95 if index < 5 else 0.4,
            outcome=outcome,
        )
        detections.append(detection)
    db.add_all(detections)

    # Two wrong answers a day ago, so the competency starts in a low band.
    yesterday = datetime.now(UTC) - timedelta(days=1)
    for exercise in mcqs[:2]:
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=exercise.id,
                correct=False,
                score=0.0,
                difficulty=3,
                answered_at=yesterday,
            )
        )
    db.commit()

    return {
        "sheet_id": str(sheet.id),
        "scan_id": str(scan.id),
        "page_id": str(page.id),
        "student_id": str(student.id),
        "detection_ids": [str(d.id) for d in detections],
    }


def _band_for(client: TestClient, tenant: Tenant, student_id: str) -> str:
    matrix = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery").json()
    cells = [c for c in matrix["cells"] if c["student_id"] == student_id]
    assert cells, "expected at least one mastery cell"
    return str(cells[0]["band"])


def test_confirm_grades_only_what_is_gradeable_and_moves_the_band(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    scan_id, student_id = ctx["scan_id"], ctx["student_id"]
    detection_ids = list(ctx["detection_ids"])  # type: ignore[arg-type]

    assert _band_for(client, tenant, str(student_id)) == "fading"

    # The teacher overrides the low-confidence reading; the machine had it wrong.
    corrected = client.patch(
        f"/api/v1/scans/{scan_id}/detections/{detection_ids[5]}",
        json={"detected_index": CORRECT_INDEX},
    )
    assert corrected.status_code == 200
    assert corrected.json()["outcome"] == "corrected"
    assert corrected.json()["corrected_at"] is not None
    assert corrected.json()["confidence"] == 1.0

    response = client.post(f"/api/v1/scans/{scan_id}/confirm")
    assert response.status_code == 200
    body = response.json()

    # Six gradeable items: five detected, one corrected. The ambiguous
    # double-bubble and the free-text item produce no attempt at all.
    assert body["attempts_created"] == 6
    assert body["students_affected"] == 1
    assert body["competencies_updated"] == 1

    attempts = db.execute(
        select(Attempt).where(Attempt.student_id == uuid.UUID(str(student_id)))
    ).scalars().all()
    assert len(attempts) == 8  # six new plus the two seeded yesterday
    assert sum(1 for a in attempts if a.correct) == 6
    assert all(a.sheet_id == uuid.UUID(str(ctx["sheet_id"])) for a in attempts[-6:])

    assert _band_for(client, tenant, str(student_id)) == "ok"

    scan = db.get(Scan, uuid.UUID(str(scan_id)))
    assert scan is not None
    assert scan.status is ScanStatus.CONFIRMED


def test_a_correction_records_who_and_when(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    detection_id = next(iter(ctx["detection_ids"]))  # type: ignore[arg-type]

    client.patch(
        f"/api/v1/scans/{ctx['scan_id']}/detections/{detection_id}",
        json={"detected_index": 3},
    )
    detection = db.get(Detection, uuid.UUID(str(detection_id)))
    assert detection is not None
    assert detection.outcome is DetectionOutcome.CORRECTED
    assert detection.corrected_by_id == tenant.teacher.id
    assert detection.corrected_at is not None
    assert detection.detected_index == 3


def test_confirming_twice_is_a_conflict(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    assert client.post(f"/api/v1/scans/{ctx['scan_id']}/confirm").status_code == 200
    again = client.post(f"/api/v1/scans/{ctx['scan_id']}/confirm")
    assert again.status_code == 409


def test_a_page_with_no_student_blocks_confirmation_until_assigned(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    page = db.get(ScanPage, uuid.UUID(str(ctx["page_id"])))
    assert page is not None
    page.student_id = None
    page.sheet_instance_id = None
    db.commit()

    blocked = client.post(f"/api/v1/scans/{ctx['scan_id']}/confirm")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["details"]["page_ids"] == [str(ctx["page_id"])]

    assigned = client.patch(
        f"/api/v1/scans/{ctx['scan_id']}/pages/{ctx['page_id']}",
        json={"student_id": str(ctx["student_id"])},
    )
    assert assigned.status_code == 200
    assert assigned.json()["student_id"] == str(ctx["student_id"])
    assert assigned.json()["sheet_instance_id"] is not None

    assert client.post(f"/api/v1/scans/{ctx['scan_id']}/confirm").status_code == 200


def test_a_detached_scan_offers_nobody_rather_than_the_whole_school(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Deleting a sheet nulls its scans' ``sheet_id`` (ondelete="SET NULL").

    The pile then has no class to scope the picker to, and the one answer that
    must never be given is "every student in the school": assigning a page to a
    child from another class files one pupil's answers under another's name.
    Offer nobody instead.
    """
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)

    offered = client.get(f"/api/v1/scans/{ctx['scan_id']}/students")
    assert offered.status_code == 200
    assert {s["uid"] for s in offered.json()} == {s.uid for s in tenant.students}

    scan = db.get(Scan, uuid.UUID(str(ctx["scan_id"])))
    assert scan is not None
    scan.sheet_id = None
    db.commit()

    detached = client.get(f"/api/v1/scans/{ctx['scan_id']}/students")
    assert detached.status_code == 200
    assert detached.json() == []

    # And the assignment itself is refused, not merely hidden from the picker.
    page = client.patch(
        f"/api/v1/scans/{ctx['scan_id']}/pages/{ctx['page_id']}",
        json={"student_id": str(ctx["student_id"])},
    )
    assert page.status_code == 422


def test_detections_are_listed_in_page_and_item_order(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    detections = client.get(f"/api/v1/scans/{ctx['scan_id']}/detections").json()
    assert [d["item_index"] for d in detections] == list(range(8))
    assert detections[6]["outcome"] == "multiple"


def test_home_counts_a_pending_scan(client: TestClient, tenant: Tenant, db: Session) -> None:
    login(client, tenant.teacher.email)
    _build_scanned_sheet(client, tenant, db)
    summary = client.get("/api/v1/home").json()["classes"][0]
    assert summary["pending_scans"] == 1
    assert summary["last_sheet_title"] == "Fractions"


def test_a_written_answer_is_corrected_with_a_verdict_not_a_bubble(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The review screen sends a verdict and a transcription for a box; the
    response carries what the machine read beside what the teacher decided."""
    login(client, tenant.teacher.email)
    ctx = _build_scanned_sheet(client, tenant, db)
    detection_id = list(ctx["detection_ids"])[-1]  # type: ignore[arg-type]  # the free-text item
    detection = db.get(Detection, uuid.UUID(str(detection_id)))
    assert detection is not None
    from alppy.models import SheetItem

    item = db.get(SheetItem, detection.sheet_item_id)
    assert item is not None
    # The builder above predates exercise_id; the pipeline always writes it.
    detection.exercise = item.exercise
    detection.crop_key = "scans/x/box.png"
    detection.transcription = detection.machine_transcription = "7/9"
    detection.verdict_correct = detection.machine_verdict_correct = False
    db.commit()

    listed = client.get(f"/api/v1/scans/{ctx['scan_id']}/detections").json()
    row = next(d for d in listed if d["id"] == detection_id)
    assert row["exercise_type"] == "open"
    assert row["transcription"] == "7/9" and row["verdict_correct"] is False
    assert row["crop_url"], "the crop is served, not its storage key"

    refused = client.patch(
        f"/api/v1/scans/{ctx['scan_id']}/detections/{detection_id}",
        json={"detected_index": 1},
    )
    assert refused.status_code == 422

    corrected = client.patch(
        f"/api/v1/scans/{ctx['scan_id']}/detections/{detection_id}",
        json={"verdict_correct": True, "transcription": "7/8"},
    ).json()
    assert corrected["outcome"] == "corrected"
    assert corrected["verdict_correct"] is True and corrected["transcription"] == "7/8"
    assert corrected["machine_verdict_correct"] is False
    assert corrected["machine_transcription"] == "7/9"
