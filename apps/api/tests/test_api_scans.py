"""Scan upload validation, teacher corrections, and confirm -> attempts -> bands."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import (
    PDF_BYTES,
    PNG_BYTES,
    Tenant,
    login,
    make_app_client,
    make_exercise,
)

from alppy.core.config import Settings
from alppy.models import Attempt, Detection, Job, Scan, ScanPage, Sheet, SheetInstance, Student
from alppy.models.enums import DetectionOutcome, ExerciseType, JobKind, JobStatus, ScanStatus

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


def test_upload_rejects_a_pile_of_too_many_files(
    db: Session,
    session_factory: sessionmaker[Session],
    storage,
    tenant: Tenant,
    sheet_id: str,
) -> None:
    """The per-file cap says nothing about how many files arrive together, and
    every one of them is held in memory for the life of the request."""
    capped = Settings(
        env="ci", secret_key="test-secret-key", max_upload_mb=1, max_upload_files=3
    )
    with make_app_client(session_factory, storage, capped) as capped_client:
        login(capped_client, tenant.teacher.email)
        response = capped_client.post(
            "/api/v1/scans",
            files=[("files", (f"IMG_{i:04d}.png", PNG_BYTES, "image/png")) for i in range(4)],
            data={"sheet_id": sheet_id},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
    assert response.json()["error"]["details"]["max_files"] == 3
    # Refused before anything was read: no scan, no job, nothing stored.
    assert db.execute(select(Scan)).scalars().all() == []


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
                person_id=student.person_id,
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


def _review_unsure_readings(client: TestClient, scan_id: str) -> list[str]:
    """Open every reading the detector was unsure of, and affirm it.

    Since D-scan-low-confidence a pile with an unreviewed `LOW_CONFIDENCE` row
    cannot be confirmed: the machine saying "I do not know" must not become a
    mark on a child without a person looking. Affirming is re-sending the same
    reading — `correct_detection` stamps `CORRECTED` whatever value it gets —
    so this is what a teacher does when they look and agree.

    Returns the ids it reviewed, so a test can assert there were some: a helper
    that silently reviewed nothing would make the tests below pass for the
    wrong reason.
    """
    pages = client.get(f"/api/v1/scans/{scan_id}").json()["pages"]
    reviewed: list[str] = []
    for page in pages:
        for detection in page["detections"]:
            if detection["outcome"] != DetectionOutcome.LOW_CONFIDENCE:
                continue
            response = client.patch(
                f"/api/v1/scans/{scan_id}/detections/{detection['id']}",
                json={"detected_index": detection["detected_index"]},
            )
            assert response.status_code == 200, response.text
            reviewed.append(detection["id"])
    return reviewed


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

    # The attempts hang off the PERSON since 0028; `student_id` is the
    # year-bound row the paper was printed for, so the lookup goes through it.
    person_id = db.get(Student, uuid.UUID(str(student_id))).person_id  # type: ignore[union-attr]
    attempts = db.execute(
        select(Attempt).where(Attempt.person_id == person_id)
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
    assert _review_unsure_readings(client, str(ctx["scan_id"]))
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

    assert _review_unsure_readings(client, str(ctx["scan_id"]))
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
    body = client.get(f"/api/v1/scans/{ctx['scan_id']}/detections").json()
    detections = body["items"]
    assert [d["item_index"] for d in detections] == list(range(8))
    assert detections[6]["outcome"] == "multiple"
    assert body["total"] == len(detections)

    # Paged: a pile is one page per pupil per sheet page, each carrying one
    # row per item, and the review screen re-reads them on every correction.
    page = client.get(f"/api/v1/scans/{ctx['scan_id']}/detections?limit=3").json()
    assert [d["item_index"] for d in page["items"]] == [0, 1, 2]
    assert page["total"] == body["total"], "total counts the pile, not the page"


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

    listed = client.get(f"/api/v1/scans/{ctx['scan_id']}/detections").json()["items"]
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


# --------------------------------------------------------------------------
# F11 · A retake joins the pile it belongs to
# --------------------------------------------------------------------------
def _upload_pile(
    client: TestClient, sheet_id: str, count: int = 3, *, db: Session | None = None
) -> str:
    response = client.post(
        "/api/v1/scans",
        files=[
            ("files", (f"IMG_{i:04d}.png", PNG_BYTES, "image/png")) for i in range(count)
        ],
        data={"sheet_id": sheet_id},
    )
    assert response.status_code == 202
    if db is not None:
        # The state a retake actually happens in: the pile has been read, and
        # the teacher is looking at the page that would not register. One run
        # at a time per pile, so leaving the job queued would (correctly) be
        # refused — see `test_a_pile_still_being_read_refuses_another_page`.
        _finish_processing(db)
    return str(response.json()["id"])


def _finish_processing(db: Session) -> None:
    for job in db.execute(select(Job).where(Job.kind == JobKind.PROCESS_SCAN)).scalars():
        job.status = JobStatus.SUCCEEDED
    db.commit()


def test_a_retake_joins_the_pile_rather_than_starting_a_second_one(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """The whole finding: three bad photographs out of thirty used to mean a
    second scan, a second review and a second confirmation for one class's
    single submission."""
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, db=db)

    response = client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("IMG_0000-retake.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 202

    scans = db.execute(select(Scan)).scalars().all()
    assert len(scans) == 1, "a retake must not create a second pile"
    assert len(scans[0].storage_keys or []) == 4
    assert "IMG_0000-retake.png" in (scans[0].original_filename or "")


def test_only_the_added_files_are_processed(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """Nothing deletes the pages already read — the teacher's corrections hang
    off those rows — so re-reading the pile would duplicate every page. The job
    says where to start."""
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, db=db)

    client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("retake.png", PNG_BYTES, "image/png")},
    )

    jobs = client.get("/api/v1/jobs?kind=process_scan").json()
    assert len(jobs) == 2, "the retake is its own piece of work"
    # Newest first: the second job starts after the three already uploaded.
    assert jobs[0]["id"] != jobs[1]["id"]


def test_the_replaced_page_is_discarded_in_the_same_breath(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """Otherwise the pile holds both photographs, and a copy with more pages
    than were printed is flagged as overflowing (B5)."""
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, count=1, db=db)

    page = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=uuid.UUID(scan_id),
        page_index=0,
        image_key="scan-pages/whatever.png",
        registered=False,
    )
    db.add(page)
    db.commit()

    response = client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("retake.png", PNG_BYTES, "image/png")},
        data={"supersedes_page_id": str(page.id)},
    )
    assert response.status_code == 202

    db.refresh(page)
    assert page.discarded is True, "the failed photograph is not one of the copy's pages"


def test_a_confirmed_pile_refuses_more_pages(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """Its grades were computed from the readings as they stood. A page added
    underneath them is a grade disagreeing with its own evidence."""
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, count=1)
    scan = db.execute(select(Scan)).scalars().one()
    scan.status = ScanStatus.CONFIRMED
    db.commit()

    response = client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("retake.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "scan_confirmed"


def test_a_colleagues_pile_is_not_one_you_can_add_to(
    client: TestClient, tenant: Tenant, sheet_id: str, colleague: Tenant
) -> None:
    """Reads as missing rather than forbidden, like every other scan route."""
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, count=1)

    login(client, colleague.teacher.email)
    response = client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("retake.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 404


def test_a_pile_still_being_read_refuses_another_page(
    client: TestClient, tenant: Tenant, sheet_id: str, db: Session
) -> None:
    """Two runs over one pile would collide.

    Page numbers and stored image keys both continue from the rows already
    written, and the worker runs four jobs at once — so a second run counting
    the same rows writes the same `page_index` twice and overwrites the first
    run's registered images. Reachable in practice, because pages appear as
    they are read: a teacher can see page 1 fail while page 20 is still going.
    """
    login(client, tenant.teacher.email)
    scan_id = _upload_pile(client, sheet_id, count=1)
    # The upload's own job is queued and has not run: the state a teacher is
    # in while watching the pile come in.

    response = client.post(
        f"/api/v1/scans/{scan_id}/pages",
        files={"files": ("retake.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "scan_processing"

    # And it is allowed again once nothing is reading the pile.
    job = db.execute(select(Job).where(Job.kind == JobKind.PROCESS_SCAN)).scalars().first()
    assert job is not None
    job.status = JobStatus.SUCCEEDED
    db.commit()

    assert (
        client.post(
            f"/api/v1/scans/{scan_id}/pages",
            files={"files": ("retake.png", PNG_BYTES, "image/png")},
        ).status_code
        == 202
    )
