"""The override rate and the confidence distribution (D8).

Both were computable from day one and neither had ever been computed. The test
that matters most here is the one about what an override *is*: `CORRECTED` is
stamped whether the teacher agreed or disagreed (T24), so counting outcomes
would measure attention and report it as error.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy.models import Detection, Scan, ScanPage
from alppy.models.enums import DetectionOutcome, ScanStatus
from alppy.services.health_signals import (
    confidence_distributions,
    override_rates,
    registration_rates,
    report,
)


@pytest.fixture
def page(db: Session, tenant: Tenant) -> ScanPage:
    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        original_filename="copies.pdf",
        storage_key="scans/copies.pdf",
        status=ScanStatus.CONFIRMED,
    )
    db.add(scan)
    db.flush()
    row = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=scan.id,
        page_index=0,
        image_key="scans/page-000.png",
        registered=True,
    )
    db.add(row)
    db.flush()
    return row


def _detection(
    db: Session,
    page: ScanPage,
    *,
    index: int,
    machine_index: int | None = 1,
    detected_index: int | None = 1,
    confidence: float = 0.9,
    reviewed: bool = False,
    machine_transcription: str | None = None,
    transcription: str | None = None,
    machine_verdict: bool | None = None,
    verdict: bool | None = None,
    age_days: int = 0,
) -> Detection:
    row = Detection(
        id=uuid.uuid4(),
        school_id=page.school_id,
        scan_page_id=page.id,
        item_index=index,
        outcome=DetectionOutcome.CORRECTED if reviewed else DetectionOutcome.DETECTED,
        detected_index=detected_index,
        machine_index=machine_index,
        machine_outcome=DetectionOutcome.DETECTED if machine_index is not None else None,
        machine_confidence=confidence,
        confidence=confidence,
        machine_transcription=machine_transcription,
        transcription=transcription,
        machine_verdict_correct=machine_verdict,
        verdict_correct=verdict,
        corrected_at=datetime.now(UTC) if reviewed else None,
    )
    db.add(row)
    db.flush()
    row.created_at = datetime.now(UTC) - timedelta(days=age_days)
    db.flush()
    return row


# --- the override rate ------------------------------------------------------


def test_a_teacher_who_looked_and_agreed_is_not_an_override(
    db: Session, page: ScanPage
) -> None:
    """The finding this whole module turns on.

    `correct_detection` stamps CORRECTED whatever value it is sent, because
    reviewing is not disagreeing: a teacher who opens a low-confidence row and
    agrees affirms by re-sending the same reading. Counting outcomes would call
    that an error and report a detector that is working as one that is not.
    """
    _detection(db, page, index=0, machine_index=2, detected_index=2, reviewed=True)

    rate = override_rates(db)[0]
    assert rate.machine_readings == 1
    assert rate.reviewed == 1
    assert rate.overridden == 0
    assert rate.override_rate == 0.0


def test_a_changed_reading_is_an_override(db: Session, page: ScanPage) -> None:
    _detection(db, page, index=0, machine_index=2, detected_index=3, reviewed=True)

    rate = override_rates(db)[0]
    assert rate.overridden == 1
    assert rate.override_rate == 1.0
    assert rate.disagreement_when_reviewed == 1.0


def test_a_corrected_verdict_on_a_written_answer_counts(
    db: Session, page: ScanPage
) -> None:
    """Three readings live on one row and any of them can be overridden
    independently — the bubble, the verdict, and the transcription."""
    _detection(
        db, page, index=0, machine_index=None, detected_index=None,
        machine_verdict=True, verdict=False, reviewed=True,
    )
    # machine_outcome is NULL without a machine_index, so this row is not a
    # machine reading at all — which is the point of the next assertion.
    assert override_rates(db) == []

    _detection(
        db, page, index=1, machine_index=1, detected_index=1,
        machine_verdict=True, verdict=False, reviewed=True,
    )
    assert override_rates(db)[0].overridden == 1


def test_a_corrected_transcription_counts_even_when_the_verdict_stands(
    db: Session, page: ScanPage
) -> None:
    """Fixing a misread word without changing the mark is still the teacher
    correcting the machine, and it is the signal that degrades first."""
    _detection(
        db, page, index=0,
        machine_transcription="3/4", transcription="3/8",
        machine_verdict=False, verdict=False, reviewed=True,
    )
    assert override_rates(db)[0].overridden == 1


def test_rows_the_machine_never_read_do_not_dilute_the_rate(
    db: Session, page: ScanPage
) -> None:
    """A pending written answer has no `machine_outcome`. Counting it in the
    denominator would make a detector look better the more work it has not
    finished."""
    _detection(db, page, index=0, machine_index=1, detected_index=2, reviewed=True)
    _detection(db, page, index=1, machine_index=None, detected_index=None)

    rate = override_rates(db)[0]
    assert rate.machine_readings == 1
    assert rate.override_rate == 1.0


def test_the_review_count_is_reported_beside_the_rate(db: Session, page: ScanPage) -> None:
    """An override rate over a pile nobody opened says nothing about the
    scanner, so the two numbers are only honest together."""
    for i in range(8):
        _detection(db, page, index=i, machine_index=1, detected_index=1)
    _detection(db, page, index=8, machine_index=1, detected_index=2, reviewed=True)
    _detection(db, page, index=9, machine_index=1, detected_index=1, reviewed=True)

    rate = override_rates(db)[0]
    assert rate.machine_readings == 10
    assert rate.reviewed == 2
    assert rate.overridden == 1
    assert rate.override_rate == pytest.approx(0.1)
    assert rate.disagreement_when_reviewed == pytest.approx(0.5)


def test_the_window_is_respected(db: Session, page: ScanPage) -> None:
    _detection(db, page, index=0, machine_index=1, detected_index=2, reviewed=True, age_days=30)
    assert override_rates(db, days=7) == []
    assert override_rates(db, days=60)[0].overridden == 1


def test_an_empty_week_is_an_empty_list_not_a_zero(db: Session) -> None:
    """A school that graded nothing has no override rate, and reporting 0%
    would read as a perfect week."""
    assert override_rates(db) == []


# --- the confidence distribution --------------------------------------------


def test_confidence_lands_in_deciles(db: Session, page: ScanPage) -> None:
    for i, confidence in enumerate([0.05, 0.15, 0.95, 0.99]):
        _detection(db, page, index=i, confidence=confidence)

    dist = confidence_distributions(db)[0]
    assert dist.buckets[0] == 1
    assert dist.buckets[1] == 1
    assert dist.buckets[9] == 2
    assert dist.total == 4


def test_a_perfect_confidence_lands_in_the_top_bucket_not_an_eleventh(
    db: Session, page: ScanPage
) -> None:
    """`cast(1.0 * 10 as int)` is 10, and there are ten buckets."""
    _detection(db, page, index=0, confidence=1.0)
    dist = confidence_distributions(db)[0]
    assert len(dist.buckets) == 10
    assert dist.buckets[9] == 1


def test_below_half_is_the_number_worth_watching(db: Session, page: ScanPage) -> None:
    """How much of the week the detector was closer to guessing than reading."""
    for i, confidence in enumerate([0.1, 0.2, 0.3, 0.8, 0.9]):
        _detection(db, page, index=i, confidence=confidence)
    assert confidence_distributions(db)[0].below_half == 3


# --- registration -----------------------------------------------------------


def test_a_page_that_did_not_register_is_counted(db: Session, tenant: Tenant, page: ScanPage) -> None:
    """A page that fails to register produces no readings at all, so a school
    whose photocopier has drifted DISAPPEARS from the override rate rather than
    showing up in it. This is the number that catches that."""
    failed = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=page.scan_id,
        page_index=1,
        image_key="scans/page-001.png",
        registered=False,
    )
    db.add(failed)
    db.flush()

    reg = registration_rates(db)[0]
    assert reg.pages == 2
    assert reg.failed == 1
    assert reg.failure_rate == pytest.approx(0.5)


# --- the report -------------------------------------------------------------


def test_the_report_runs_and_names_the_schools_it_saw(db: Session, page: ScanPage) -> None:
    _detection(db, page, index=0, machine_index=1, detected_index=2, reviewed=True)
    assert report(db, days=7) == 1


def test_the_report_is_a_no_op_on_an_empty_deployment(db: Session) -> None:
    assert report(db, days=7) == 0
