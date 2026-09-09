"""The two read-only reports: what a class scored, and which item read badly.

Both are computed fresh over rows that already exist, so the thing worth
testing is not that they add up — it is that they agree with the per-sheet
numbers already on every sheet response, and that "nothing graded yet" never
reads as a zero.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant
from test_scan_processing import _render_copy, _render_copy_wrong, _run, _sheet

from alppy.models.enums import DetectionOutcome
from alppy.schemas import DetectionCorrection
from alppy.services import results_service, scan_service, sheet_service
from alppy.storage import LocalStorage


def test_a_class_total_agrees_with_each_sheets_own_numbers(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rollup must not be a second, independent computation. If it can
    disagree with `points_totals_for_sheet`, one of the two screens is lying."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    sheet.default_points_correct = 2.0
    db.commit()
    uid = tenant.students[0].uid
    scan = _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    per_sheet = sheet_service.points_totals_for_sheet(db, tenant.school.id, sheet)
    report = sheet_service.class_points_totals(db, tenant.scope, tenant.school_class.id)

    student = next(s for s in tenant.students if s.uid == uid)
    assert report.students[student.id].earned == per_sheet[student.id].earned
    assert report.students[student.id].possible == per_sheet[student.id].possible


def test_a_student_graded_on_nothing_yet_earns_null_not_zero(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A term with two of five sheets marked must not read as three failures."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    scan = _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    report = sheet_service.class_points_totals(db, tenant.scope, tenant.school_class.id)
    graded = next(s for s in tenant.students if s.uid == uid)
    ungraded = [s for s in tenant.students if s.uid != uid]

    assert report.students[graded.id].earned is not None
    for student in ungraded:
        entry = report.students.get(student.id)
        assert entry is not None, "every copy of the sheet is accounted for"
        assert entry.earned is None, "never scanned is not the same as scored zero"
        assert entry.possible > 0, "the paper was still worth something"


def test_a_sheet_nobody_has_scanned_has_no_average(
    db: Session, tenant: Tenant
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    db.commit()
    report = sheet_service.class_points_totals(db, tenant.scope, tenant.school_class.id)
    entry = next(s for s in report.sheets if s.sheet_id == sheet.id)
    assert entry.average_ratio is None


def test_the_class_rollup_can_be_narrowed_to_one_subject(
    db: Session, tenant: Tenant
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    db.commit()
    same = sheet_service.class_points_totals(
        db, tenant.scope, tenant.school_class.id, subject_id=tenant.subject.id
    )
    assert any(s.sheet_id == sheet.id for s in same.sheets)


def test_item_confidence_counts_copies_not_students(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The report names a printed item, never a child: one pupil misreading
    question 7 is a pupil, twenty is a bad photocopy."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    db.commit()

    items = scan_service.confidence_by_item(db, tenant.scope, sheet.id)
    assert items, "a scanned sheet reports its items"
    assert all(item.copies_read >= 1 for item in items)
    # Nothing here is keyed by a student.
    assert not any(hasattr(item, "student_id") for item in items)


def test_a_corrected_item_leaves_the_unsure_column_for_the_corrected_one(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A high corrected count is itself the signal that an item printed badly —
    it must not also keep counting as still-unsure work in the queue."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    scan = _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    detection = scan.pages[0].detections[0]
    scan_service.correct_detection(
        db,
        tenant.school.id,
        tenant.teacher.id,
        scan.id,
        detection.id,
        DetectionCorrection(detected_index=0),
    )
    db.commit()
    assert detection.outcome is DetectionOutcome.CORRECTED

    items = scan_service.confidence_by_item(db, tenant.scope, sheet.id)
    entry = next(i for i in items if i.exercise_id == detection.exercise_id)
    assert entry.corrected == 1
    assert entry.low_confidence == 0


def test_a_copy_photographed_twice_is_counted_once(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule confirmation applies to grades, applied to a report: a
    re-photographed page supersedes the blurry one rather than doubling it."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    _run(db, storage, tenant, sheet, _render_copy_wrong(db, sheet, uid), monkeypatch)
    db.commit()

    items = scan_service.confidence_by_item(db, tenant.scope, sheet.id)
    for item in items:
        assert item.copies_read == 1, "one reading per student per item"


def test_the_reports_are_reachable_over_http(
    client: TestClient,  # noqa: F405
    db: Session,
    tenant: Tenant,
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    db.commit()
    login(client, tenant.teacher.email)  # noqa: F405

    points = client.get(f"/api/v1/classes/{tenant.school_class.id}/points")
    assert points.status_code == 200, points.text
    body = points.json()
    assert body["class_id"] == str(tenant.school_class.id)
    assert any(s["sheet_id"] == str(sheet.id) for s in body["sheets"])

    confidence = client.get(f"/api/v1/sheets/{sheet.id}/confidence")
    assert confidence.status_code == 200, confidence.text
    assert confidence.json()["sheet_id"] == str(sheet.id)


def test_an_item_on_the_second_page_does_not_hide_the_first_pages_item(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`item_index` is page-local and restarts at 0 on every physical page (I6).

    Keying the report on it makes page two's first item collide with page one's
    and drop a question from the report entirely — which is what happened, on a
    real pile, before this test existed.
    """
    # Enough items to force a second physical page for at least one copy.
    sheet, exercises = _sheet(db, tenant, answers=[0, 1, 2, 3] * 5)
    uid = tenant.students[0].uid
    _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    db.commit()

    items = scan_service.confidence_by_item(db, tenant.scope, sheet.id)
    reported = {item.exercise_id for item in items}
    for exercise in exercises:
        assert exercise.id in reported, (
            f"exercise {exercise.id} vanished from the report — a page-local "
            "index collision is hiding it"
        )
    numbers = [item.number for item in items if item.number is not None]
    assert len(numbers) == len(set(numbers)), "each printed question appears once"


# --------------------------------------------------------------------------
# One pupil's copy, question by question
# --------------------------------------------------------------------------
def test_a_students_copy_shows_what_they_put_and_what_was_expected(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    uid = tenant.students[0].uid
    student = next(s for s in tenant.students if s.uid == uid)
    scan = _run(db, storage, tenant, sheet, _render_copy(db, sheet, uid), monkeypatch)
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    view = results_service.student_sheet_breakdown(db, tenant.scope, student.id, sheet.id)

    assert len(view.items) == 2
    for item in view.items:
        # Both answers are readable text, not raw indices.
        assert item.given, "the pupil's answer is rendered, not just an index"
        assert item.expected, "the expected answer is rendered too"
        assert item.given == item.expected, "this copy was answered correctly"
        assert item.correct is True
        assert item.points_earned == 1.0
        assert item.points_possible == 1.0
    assert view.points_earned == 2.0
    assert view.points_possible == 2.0
    assert view.scan_id == scan.id


def test_an_unmarked_copy_shows_no_points_rather_than_zero(
    db: Session, tenant: Tenant
) -> None:
    """The rule the whole screen turns on: an item with no attempt is not an
    item scored zero. Nobody has asserted anything about it."""
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    db.commit()
    student = tenant.students[0]

    view = results_service.student_sheet_breakdown(db, tenant.scope, student.id, sheet.id)

    assert view.points_earned is None, "never 0.0 for a copy nobody has marked"
    assert view.points_possible > 0, "the paper was still worth something"
    for item in view.items:
        assert item.correct is None
        assert item.points_earned is None
        assert item.given is None


def test_a_wrong_answer_shows_both_answers_and_the_penalty(
    db: Session, storage: LocalStorage, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    sheet.default_points_penalty = 0.5
    db.commit()
    uid = tenant.students[0].uid
    student = next(s for s in tenant.students if s.uid == uid)
    scan = _run(db, storage, tenant, sheet, _render_copy_wrong(db, sheet, uid), monkeypatch)
    scan_service.confirm_scan(db, tenant.scope, scan.id)
    db.commit()

    view = results_service.student_sheet_breakdown(db, tenant.scope, student.id, sheet.id)
    for item in view.items:
        assert item.correct is False
        assert item.points_earned == -0.5, "the signed score, as the record holds it"
        assert item.given != item.expected, "both answers are shown, and they differ"
    # The per-item scores stay signed; only the total floors.
    assert view.points_earned == 0.0


def test_the_students_copy_is_reachable_over_http(
    client: TestClient,  # noqa: F405
    db: Session,
    tenant: Tenant,
) -> None:
    sheet, _ = _sheet(db, tenant, answers=[0, 1])
    db.commit()
    login(client, tenant.teacher.email)  # noqa: F405
    student = tenant.students[0]

    response = client.get(f"/api/v1/students/{student.id}/sheets/{sheet.id}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sheet_id"] == str(sheet.id)
    assert body["points_earned"] is None
    assert len(body["items"]) == 2
    assert all("statement" in item for item in body["items"])
