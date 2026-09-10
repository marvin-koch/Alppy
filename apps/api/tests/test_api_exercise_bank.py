"""`GET /exercises` — the corpus, reachable without opening a document.

Every exercise used to be reachable only THROUGH the source it came from, so
"every fractions item at difficulty 2, wherever it came from" meant opening
each document and filtering it by hand — and an exercise the teacher wrote
themselves, which has no source at all, was reachable from nothing but the
sheet it was first used on (audit 02, H9).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Competency
from alppy.models.enums import ExerciseOrigin, ExerciseType


def _bank(client: TestClient, query: str = "") -> dict:
    response = client.get(f"/api/v1/exercises{query}")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_bank_lists_the_schools_corpus_without_naming_a_source(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    a = make_exercise(db, tenant, statement="1/2 + 1/4 ?")
    b = make_exercise(db, tenant, statement="Aire du rectangle ?")

    login(client, tenant.teacher.email)
    body = _bank(client)
    assert {item["id"] for item in body["items"]} >= {str(a.id), str(b.id)}
    assert body["total"] >= 2
    assert body["facets"]["total"] >= 2


def test_another_schools_exercises_are_not_in_my_bank(
    client: TestClient, db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    """Staffroom-shared means the SCHOOL's corpus, not everyone's."""
    theirs = make_exercise(db, other_tenant, statement="Chez nous")

    login(client, tenant.teacher.email)
    assert str(theirs.id) not in {item["id"] for item in _bank(client)["items"]}


def test_the_bank_filters_on_a_competency_through_the_m2m(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """What an exercise CREDITS, not where it sits.

    `Exercise.chapter_id` is where a row was filed; `exercise_competency` is
    what it counts towards, and they are not interchangeable.
    """
    tagged = make_exercise(db, tenant, statement="Fractions")
    untagged = make_exercise(
        db, tenant, statement="Sans competence", with_competency=False
    )

    login(client, tenant.teacher.email)
    body = _bank(client, f"?competency_id={tenant.competency.id}")
    ids = {item["id"] for item in body["items"]}
    assert str(tagged.id) in ids
    assert str(untagged.id) not in ids


def test_the_competency_filter_repeats(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    other = Competency(
        id=uuid.uuid4(),
        curriculum=tenant.competency.curriculum,
        code="MSN.99",
        parent_id=None,
        subject_key="mathematics",
        cycle=3,
        labels={"fr": "Aires"},
        description={},
    )
    db.add(other)
    db.flush()
    first = make_exercise(db, tenant, statement="Fractions")
    second = make_exercise(db, tenant, statement="Aires", with_competency=False)
    second.competencies = [other]
    db.commit()

    login(client, tenant.teacher.email)
    body = _bank(
        client, f"?competency_id={tenant.competency.id}&competency_id={other.id}"
    )
    ids = {item["id"] for item in body["items"]}
    assert {str(first.id), str(second.id)} <= ids


def test_the_bank_finds_the_items_waiting_for_approval(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`approved=false` is the review queue.

    An AI-generated exercise is never printed without the second look
    `approved_at` exists to require, and until now there was no way to ask for
    the ones still waiting.
    """
    generated = make_exercise(db, tenant, statement="Genere")
    generated.origin = ExerciseOrigin.AI_GENERATED
    generated.approved_at = None
    db.commit()

    login(client, tenant.teacher.email)
    waiting = _bank(client, "?approved=false")
    assert str(generated.id) in {item["id"] for item in waiting["items"]}

    approved = _bank(client, "?approved=true")
    assert str(generated.id) not in {item["id"] for item in approved["items"]}


def test_a_discarded_exercise_is_never_in_the_bank(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    from datetime import UTC, datetime

    gone = make_exercise(db, tenant, statement="Jetee")
    gone.discarded_at = datetime.now(UTC)
    db.commit()

    login(client, tenant.teacher.email)
    assert str(gone.id) not in {item["id"] for item in _bank(client)["items"]}


def test_the_untagged_sentinel_reaches_the_rows_no_theme_owns(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`chapter_id=none` is a real filter, distinct from the parameter being
    absent — a large minority of a real textbook has no Theme at all (D59)."""
    loose = make_exercise(db, tenant, statement="Sans theme")
    assert loose.chapter_id is None

    login(client, tenant.teacher.email)
    body = _bank(client, "?chapter_id=none")
    assert str(loose.id) in {item["id"] for item in body["items"]}

    bad = client.get("/api/v1/exercises?chapter_id=not-a-uuid")
    assert bad.status_code == 422


def test_the_type_facets_report_what_selecting_would_give(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """A chip counts what choosing it yields, so the facets are computed with
    every filter applied EXCEPT the type itself."""
    make_exercise(db, tenant, statement="QCM", kind=ExerciseType.MCQ)
    make_exercise(
        db,
        tenant,
        statement="Vrai ou faux",
        kind=ExerciseType.TRUE_FALSE,
        answer_index=None,
        answer_bool=True,
    )

    login(client, tenant.teacher.email)
    body = _bank(client, "?type=mcq")
    assert all(item["type"] == "mcq" for item in body["items"])
    # The facet block still counts the true/false rows the filter excluded.
    assert body["facets"]["true_false"] >= 1
    assert body["facets"]["mcq"] >= 1


def test_the_bank_pages(client: TestClient, db: Session, tenant: Tenant) -> None:
    for n in range(3):
        make_exercise(db, tenant, statement=f"Exercice {n}")

    login(client, tenant.teacher.email)
    first = _bank(client, "?limit=2")
    assert len(first["items"]) == 2
    assert first["total"] >= 3
    assert first["limit"] == 2 and first["offset"] == 0

    second = _bank(client, "?limit=2&offset=2")
    assert {i["id"] for i in second["items"]}.isdisjoint({i["id"] for i in first["items"]})
