"""A reading the machine was unsure of is not a grade until a person looks.

Before this, `LOW_CONFIDENCE` was counted for a report and gated nothing. A
teacher who confirmed a pile without opening it turned every unsure reading
into a mark — silently, and on the one axis where the product promises not to
guess about a child. The audit's T24 found that no test stated the behaviour in
*either* direction, which is the worse problem: the tradeoff is arguable, and
an arguable tradeoff that nobody wrote down is an accident.

The decision (Q4) is that it blocks. What makes that affordable rather than a
wall in front of a thirty-copy pile is that **reviewing is not disagreeing**:
`correct_detection` stamps `CORRECTED` whatever value it is sent, so a teacher
who looks and agrees affirms by re-sending the same reading. The gate asks for
a person's attention, not for a different answer.

The shape is deliberately unlike the other refusals in `confirm_scan`. An
unassigned page names `page_ids`; this names `detection_ids`, because the thing
the teacher has to go and open is a row on the review screen, not a page.

What it must NOT block is the other three outcomes, and they are each here for
a different reason:

* `DETECTED` — a reading the detector stands behind.
* `CORRECTED` — a teacher's own word, which is the whole point of reviewing.
* `MULTIPLE` / `NOT_GRADEABLE` / `BLANK` — honest refusals that score nothing
  and are counted as skipped. Blocking on those would stop a pile because a
  child left an item empty.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise, make_paper_trail

from alppy.api.errors import ApiError
from alppy.models import Detection, ScanPage
from alppy.models.enums import DetectionOutcome, ScanStatus
from alppy.services import scan_service


@pytest.fixture
def pile(db: Session, tenant: Tenant) -> tuple[uuid.UUID, Detection]:
    """A scan ready to confirm, with one detection a test can set the outcome of.

    TWO detections, not one, and the second is load-bearing. `confirm_scan`
    already refuses a pile where nothing at all could be matched to a question —
    a different and correct rule — so a pile holding only the row under test
    would fail that guard for outcomes that grade nothing (`MULTIPLE`), and the
    test would be reading the wrong refusal. The companion is always gradeable,
    so what is left is the low-confidence rule alone.

    A second *exercise* rather than a second item on the same one:
    `uq_attempt_person_exercise_sheet` allows one attempt per (person, exercise,
    sheet).
    """
    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    _sheet, scan, detection = make_paper_trail(db, tenant, exercise, tenant.students[0])

    companion_exercise = make_exercise(db, tenant, statement="5/6 - 1/6 ?")
    db.add(
        Detection(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            scan_page_id=detection.scan_page_id,
            exercise_id=companion_exercise.id,
            item_index=1,
            detected_index=0,
            confidence=0.97,
            outcome=DetectionOutcome.DETECTED,
        )
    )
    scan.status = ScanStatus.NEEDS_REVIEW
    db.flush()
    db.commit()
    return scan.id, detection


def _confirm(db: Session, tenant: Tenant, scan_id: uuid.UUID) -> object:
    return scan_service.confirm_scan(db, tenant.scope, scan_id)


def test_an_unreviewed_low_confidence_reading_blocks_the_pile(
    db: Session, tenant: Tenant, pile: tuple[uuid.UUID, Detection]
) -> None:
    """The invariant, stated. Confirming must refuse, and say which row."""
    scan_id, detection = pile
    detection.outcome = DetectionOutcome.LOW_CONFIDENCE
    db.flush()

    with pytest.raises(ApiError) as excinfo:
        _confirm(db, tenant, scan_id)

    assert excinfo.value.code == "scan_low_confidence_unreviewed"
    assert excinfo.value.details["detection_ids"] == [str(detection.id)]


def test_the_pile_is_not_confirmed_by_the_attempt_that_was_refused(
    db: Session, tenant: Tenant, pile: tuple[uuid.UUID, Detection]
) -> None:
    """A refusal that had already written half the attempts would be worse than
    no gate: the teacher would see an error and a partly graded pile."""
    scan_id, detection = pile
    detection.outcome = DetectionOutcome.LOW_CONFIDENCE
    db.flush()

    with pytest.raises(ApiError):
        _confirm(db, tenant, scan_id)

    scan = scan_service.get_scan(db, tenant.scope, scan_id)
    assert scan.status is not ScanStatus.CONFIRMED


def test_reviewing_the_reading_unblocks_it_without_changing_the_answer(
    db: Session, tenant: Tenant, pile: tuple[uuid.UUID, Detection]
) -> None:
    """The half that makes the gate affordable.

    The teacher looks, agrees, and re-sends the same reading. `CORRECTED` is a
    statement about who is responsible for the value, not about the value
    having changed — which is why agreeing is a legitimate review and not a
    loophole.
    """
    scan_id, detection = pile
    detection.outcome = DetectionOutcome.LOW_CONFIDENCE
    unchanged = detection.detected_index
    db.flush()

    scan_service.correct_detection(
        db,
        tenant.school.id,
        tenant.teacher.id,
        scan_id,
        detection.id,
        _correction(unchanged),
    )
    db.flush()

    _confirm(db, tenant, scan_id)

    scan = scan_service.get_scan(db, tenant.scope, scan_id)
    assert scan.status is ScanStatus.CONFIRMED
    assert detection.detected_index == unchanged, "reviewing changed the reading"
    assert detection.corrected_by_id == tenant.teacher.id


@pytest.mark.parametrize(
    "outcome",
    [
        DetectionOutcome.DETECTED,
        DetectionOutcome.CORRECTED,
        DetectionOutcome.BLANK,
        DetectionOutcome.MULTIPLE,
        DetectionOutcome.NOT_GRADEABLE,
    ],
)
def test_every_other_outcome_still_confirms(
    db: Session,
    tenant: Tenant,
    pile: tuple[uuid.UUID, Detection],
    outcome: DetectionOutcome,
) -> None:
    """The gate is about "I do not know", not about "there is nothing here".

    A pile must not stop because a child left an item blank or filled two
    bubbles — those score nothing and are counted as skipped, which is the
    honest answer and needs no one's attention.
    """
    scan_id, detection = pile
    detection.outcome = outcome
    db.flush()

    _confirm(db, tenant, scan_id)

    assert scan_service.get_scan(db, tenant.scope, scan_id).status is ScanStatus.CONFIRMED


def test_a_discarded_page_does_not_hold_the_pile(
    db: Session, tenant: Tenant, pile: tuple[uuid.UUID, Detection]
) -> None:
    """A re-shot copy or a lens-cap frame is not part of the pile.

    Same rule the unassigned-page guard already follows; asserted here because
    a gate that ignored it would make a discarded page unreviewable AND
    blocking, with no screen to open.
    """
    scan_id, detection = pile
    detection.outcome = DetectionOutcome.LOW_CONFIDENCE
    page = db.get(ScanPage, detection.scan_page_id)
    assert page is not None
    page.discarded_at = datetime.now(UTC)
    db.flush()

    _confirm(db, tenant, scan_id)

    assert scan_service.get_scan(db, tenant.scope, scan_id).status is ScanStatus.CONFIRMED


def _correction(index: int | None) -> object:
    from alppy.schemas import DetectionCorrection

    return DetectionCorrection(detected_index=index)
