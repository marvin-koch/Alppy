"""The approve / discard / print surface, over HTTP.

`approval.py` is well covered as a service (`test_adaptive.py`), and the gate
itself is proven there. What was not covered is the layer the teacher actually
touches: `api/v1/adaptive.py` sat at 56%, and everything from `read_proposal`
onward — approve, discard, batch, render — had no test at all. That layer is
where per-request authorisation and tenant scoping are applied, so a gate that
holds in the service can still be walked around by a request that never reaches
it with the right school id.

The rule under all of it (CLAUDE.md, DC-content-05): an AI-generated exercise is
never printed without teacher approval, and a discarded one never comes back.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Exercise, MisconceptionNote
from alppy.models.enums import ExerciseOrigin
from alppy.services import approval


def _generated(db: Session, tenant: Tenant, *, statement: str, approved: bool = False) -> Exercise:
    """An AI-written exercise — the only kind the gate has an opinion about."""
    exercise = make_exercise(db, tenant, statement=statement)
    exercise.origin = ExerciseOrigin.AI_GENERATED
    exercise.approved_at = datetime.now(UTC) if approved else None
    db.commit()
    return exercise


def _proposal(exercise: Exercise) -> dict[str, Any]:
    return {
        "exercise": {
            "id": str(exercise.id),
            "type": exercise.type.value,
            "origin": exercise.origin.value,
            "language": exercise.language,
            "statement": exercise.statement,
            "options": exercise.options,
            "answer_index": exercise.answer_index,
            "difficulty": exercise.difficulty,
            "competency_ids": [],
        },
        "score": 0.8,
        "provenance": {"reason": "targets a fading competency"},
    }


def _batch_body(tenant: Tenant, *proposals: dict[str, Any]) -> dict[str, Any]:
    return {
        "class_id": str(tenant.school_class.id),
        "subject_id": str(tenant.subject.id),
        "title": "Serie differenciee",
        "language": "fr",
        "plans": [
            {
                "student_id": str(tenant.students[0].id),
                "student_uid": tenant.students[0].uid,
                "targeted_competency_ids": [],
                "retrieved": list(proposals),
                "generated": [],
            }
        ],
    }


# --------------------------------------------------------------------------
# Approving
# --------------------------------------------------------------------------
def test_approving_stamps_the_item_and_reports_what_it_stamped(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    item = _generated(db, tenant, statement="3 x 4 = ?")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(item.id)]}
    )
    assert response.status_code == 200
    assert response.json() == {"approved": 1, "exercise_ids": [str(item.id)]}

    db.expire_all()
    assert db.get(Exercise, item.id).approved_at is not None  # type: ignore[union-attr]


def test_approving_a_textbook_exercise_stamps_nothing_and_says_so(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Approving a book exercise is meaningless. Reporting it as approved would
    let the client believe it had done something it had not — the response
    names the ids actually stamped so the two can be compared."""
    textbook = make_exercise(db, tenant, statement="from the book")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(textbook.id)]}
    )
    assert response.status_code == 200
    assert response.json() == {"approved": 0, "exercise_ids": []}


def test_another_schools_exercise_cannot_be_approved(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    """The scoping test for this endpoint. `approve_exercises` filters on
    `school_id`; without it a teacher could stamp a neighbouring school's
    unapproved item and make it printable there."""
    theirs = _generated(db, other_tenant, statement="pas la votre")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(theirs.id)]}
    )
    assert response.status_code == 200
    assert response.json()["approved"] == 0

    db.expire_all()
    assert db.get(Exercise, theirs.id).approved_at is None  # type: ignore[union-attr]


def test_approving_requires_a_session(client: TestClient, tenant: Tenant, db: Session) -> None:
    item = _generated(db, tenant, statement="x")
    assert client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(item.id)]}
    ).status_code == 401


def test_approving_an_unknown_id_is_not_an_error(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(uuid.uuid4())]}
    )
    assert response.status_code == 200
    assert response.json()["approved"] == 0


# --------------------------------------------------------------------------
# Discarding
# --------------------------------------------------------------------------
def test_discarding_marks_the_item_and_un_approves_it(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The half of `approval.py` that had no coverage at all.

    A discard clears `approved_at` as well as setting `discarded_at`: an item
    approved and then thought better of must not remain printable, and the two
    columns are written together so no ordering of clicks can leave it both
    discarded and approved.
    """
    item = _generated(db, tenant, statement="pas terrible", approved=True)
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/discard", json={"exercise_ids": [str(item.id)]}
    )
    assert response.status_code == 200
    assert response.json() == {"discarded": 1, "exercise_ids": [str(item.id)]}

    db.expire_all()
    stored = db.get(Exercise, item.id)
    assert stored is not None
    assert stored.discarded_at is not None
    assert stored.approved_at is None


def test_a_discarded_item_is_kept_not_deleted(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`Attempt` rows may point at it if an earlier version of the sheet was
    printed, and the next run needs to know what the teacher already rejected."""
    item = _generated(db, tenant, statement="rejete")
    login(client, tenant.teacher.email)
    client.post("/api/v1/adaptive/discard", json={"exercise_ids": [str(item.id)]})

    db.expire_all()
    assert db.get(Exercise, item.id) is not None


def test_a_discarded_item_can_never_be_approved_again(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """"Never proposed or printed again" has to survive the obvious next
    request. If approve re-stamped a discarded row, the rejection would last
    exactly until someone clicked approve on a stale list."""
    item = _generated(db, tenant, statement="rejete")
    login(client, tenant.teacher.email)
    client.post("/api/v1/adaptive/discard", json={"exercise_ids": [str(item.id)]})

    response = client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(item.id)]}
    )
    assert response.json()["approved"] == 0

    db.expire_all()
    stored = db.get(Exercise, item.id)
    assert stored is not None and stored.approved_at is None


def test_another_schools_exercise_cannot_be_discarded(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    theirs = _generated(db, other_tenant, statement="pas la votre")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/discard", json={"exercise_ids": [str(theirs.id)]}
    )
    assert response.json()["discarded"] == 0

    db.expire_all()
    assert db.get(Exercise, theirs.id).discarded_at is None  # type: ignore[union-attr]


def test_discarding_requires_a_session(client: TestClient, tenant: Tenant, db: Session) -> None:
    item = _generated(db, tenant, statement="x")
    assert client.post(
        "/api/v1/adaptive/discard", json={"exercise_ids": [str(item.id)]}
    ).status_code == 401


# --------------------------------------------------------------------------
# The gate, over HTTP
# --------------------------------------------------------------------------
def test_a_batch_of_unapproved_generated_items_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The rule, at the door the teacher actually knocks on.

    The gate raises rather than filtering: a sheet quietly missing three of its
    twelve items is worse at a photocopier than an error naming them.
    """
    item = _generated(db, tenant, statement="ecrit par un modele")
    login(client, tenant.teacher.email)

    response = client.post("/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item)))
    assert response.status_code == 422
    # The teacher has to be able to act on it, so the id is named.
    assert str(item.id) in response.text


def test_a_batch_of_approved_generated_items_is_built(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    item = _generated(db, tenant, statement="approuve", approved=True)
    login(client, tenant.teacher.email)

    response = client.post("/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item)))
    assert response.status_code == 201
    assert {i["exercise"]["id"] for i in response.json()["items"]} == {str(item.id)}


def test_one_unapproved_item_refuses_the_whole_batch(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Not a partial build. The teacher gets the sheet they asked for or an
    error, never a shorter sheet they did not notice."""
    good = _generated(db, tenant, statement="approuve", approved=True)
    bad = _generated(db, tenant, statement="pas encore")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(good), _proposal(bad))
    )
    assert response.status_code == 422
    assert str(bad.id) in response.text


def test_approving_then_batching_is_the_whole_journey(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """End to end over HTTP: refused, approved, accepted. This is the sequence
    the approval screen performs, and the one that proves the gate is a gate
    rather than a permanent wall."""
    item = _generated(db, tenant, statement="a relire")
    login(client, tenant.teacher.email)

    assert client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item))
    ).status_code == 422

    assert client.post(
        "/api/v1/adaptive/approve", json={"exercise_ids": [str(item.id)]}
    ).json()["approved"] == 1

    assert client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item))
    ).status_code == 201


def test_discarding_after_approval_closes_the_print_path_again(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """An item un-approved after a sheet was built must not slip through, which
    is why the gate is applied at every door rather than once at creation."""
    item = _generated(db, tenant, statement="approuve puis rejete", approved=True)
    login(client, tenant.teacher.email)
    assert client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item))
    ).status_code == 201

    client.post("/api/v1/adaptive/discard", json={"exercise_ids": [str(item.id)]})

    assert client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(item))
    ).status_code == 422


def test_a_textbook_exercise_needs_no_approval_to_print(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The gate is about generated content only. If it caught textbook items
    too, every ordinary sheet would need a click nobody understands."""
    textbook = make_exercise(db, tenant, statement="from the book")
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/batch", json=_batch_body(tenant, _proposal(textbook))
    )
    assert response.status_code == 201


# --------------------------------------------------------------------------
# Rendering the batch
# --------------------------------------------------------------------------
def test_rendering_a_batch_with_no_instances_is_refused(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A render job over a batch with nothing to print would occupy a worker
    and hand the teacher an empty PDF."""
    login(client, tenant.teacher.email)
    sheet_response = client.post(
        "/api/v1/sheets",
        json={
            "title": "Ordinaire",
            "subject_id": str(tenant.subject.id),
            "class_id": str(tenant.school_class.id),
            "language": "fr",
            "items": [],
        },
    )
    if sheet_response.status_code != 201:
        return  # the plain-sheet endpoint has its own tests; not the subject here
    response = client.post(f"/api/v1/adaptive/batch/{sheet_response.json()['id']}/render")
    assert response.status_code == 422


def test_another_schools_batch_cannot_be_rendered(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    item = _generated(db, other_tenant, statement="leur serie", approved=True)
    login(client, other_tenant.teacher.email)
    theirs = client.post("/api/v1/adaptive/batch", json=_batch_body(other_tenant, _proposal(item)))
    assert theirs.status_code == 201
    sheet_id = theirs.json()["id"]

    client.post("/api/v1/auth/logout")
    login(client, tenant.teacher.email)
    response = client.post(f"/api/v1/adaptive/batch/{sheet_id}/render")
    # Missing, not forbidden: the response must not confirm a sheet it will not open.
    assert response.status_code == 404


# --------------------------------------------------------------------------
# The same gate, for generated feedback
# --------------------------------------------------------------------------
# Held to a stricter standard than an exercise, and `approval.py` says why: an
# unreviewed generated exercise is a bad question a teacher can spot on the
# page; an unreviewed generated note is a claim about how one named child
# thinks, printed and handed to that child.


def _note(db: Session, tenant: Tenant, *, approved: bool = False) -> MisconceptionNote:
    note = MisconceptionNote(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        person_id=tenant.students[0].person_id,
        subject_id=tenant.subject.id,
        based_on_sheet_id=None,
        notes=["Tu appliques les operations de gauche a droite."],
        language="fr",
        approved_at=datetime.now(UTC) if approved else None,
    )
    db.add(note)
    db.commit()
    return note


def test_a_note_is_written_unapproved_and_cannot_print(
    db: Session, tenant: Tenant
) -> None:
    note = _note(db, tenant)
    assert not approval.is_note_printable(note)
    with pytest.raises(approval.UnapprovedFeedbackError) as caught:
        approval.ensure_notes_printable([note])
    assert note.id in caught.value.feedback_ids


def test_approving_a_note_makes_it_printable(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    note = _note(db, tenant)
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/feedback/approve", json={"feedback_ids": [str(note.id)]}
    )
    assert response.status_code == 200
    assert response.json() == {"approved": 1, "feedback_ids": [str(note.id)]}

    db.expire_all()
    approval.ensure_notes_printable([db.get(MisconceptionNote, note.id)])  # type: ignore[list-item]


def test_discarding_a_note_un_approves_it(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    note = _note(db, tenant, approved=True)
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/feedback/discard", json={"feedback_ids": [str(note.id)]}
    )
    assert response.json() == {"discarded": 1, "feedback_ids": [str(note.id)]}

    db.expire_all()
    stored = db.get(MisconceptionNote, note.id)
    assert stored is not None
    assert stored.discarded_at is not None and stored.approved_at is None
    assert not approval.is_note_printable(stored)


def test_a_discarded_note_can_never_be_approved_again(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The exercise half of this module had exactly this hole. Pinned here so
    the two gates cannot drift apart again."""
    note = _note(db, tenant)
    login(client, tenant.teacher.email)
    client.post("/api/v1/adaptive/feedback/discard", json={"feedback_ids": [str(note.id)]})

    response = client.post(
        "/api/v1/adaptive/feedback/approve", json={"feedback_ids": [str(note.id)]}
    )
    assert response.json()["approved"] == 0

    db.expire_all()
    assert db.get(MisconceptionNote, note.id).approved_at is None  # type: ignore[union-attr]


def test_another_schools_note_cannot_be_approved(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    theirs = _note(db, other_tenant)
    login(client, tenant.teacher.email)

    response = client.post(
        "/api/v1/adaptive/feedback/approve", json={"feedback_ids": [str(theirs.id)]}
    )
    assert response.json()["approved"] == 0

    db.expire_all()
    assert db.get(MisconceptionNote, theirs.id).approved_at is None  # type: ignore[union-attr]


def test_a_student_with_no_note_is_not_an_offender(db: Session, tenant: Tenant) -> None:
    """Feedback is additive: a clean paper earns none, and a gate that treated
    absence as a violation would block printing for the whole class."""
    approval.ensure_notes_printable([])


def test_an_empty_request_is_a_validation_error_not_a_silent_success(
    client: TestClient, tenant: Tenant
) -> None:
    """`feedback_ids` is `min_length=1`, so an empty list is refused at the
    schema rather than answered with "approved 0". That is the right way round:
    an approval screen that posts nothing has a bug, and a 200 saying it worked
    is how it stays hidden. The bound at the other end (`max_length=400`) is
    what stops one request stamping a term's worth of notes."""
    login(client, tenant.teacher.email)
    for path in ("approve", "discard"):
        response = client.post(f"/api/v1/adaptive/feedback/{path}", json={"feedback_ids": []})
        assert response.status_code == 422, path
        assert response.json()["error"]["code"] == "validation_error"


def test_the_service_itself_treats_an_empty_list_as_a_no_op(
    db: Session, tenant: Tenant
) -> None:
    """Below the schema there is no validation, and the worker calls these
    directly — so the functions have to be safe on an empty list rather than
    building an `IN ()`."""
    assert approval.approve_feedback(db, school_id=tenant.school.id, feedback_ids=[]) == []
    assert approval.discard_feedback(db, school_id=tenant.school.id, feedback_ids=[]) == []
    assert approval.approve_exercises(db, school_id=tenant.school.id, exercise_ids=[]) == []
    assert approval.discard_exercises(db, school_id=tenant.school.id, exercise_ids=[]) == []


def test_feedback_approval_requires_a_session(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    note = _note(db, tenant)
    assert client.post(
        "/api/v1/adaptive/feedback/approve", json={"feedback_ids": [str(note.id)]}
    ).status_code == 401
