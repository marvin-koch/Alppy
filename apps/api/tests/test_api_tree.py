"""The curriculum tree: Class -> Branch -> Competence -> Theme.

The navigation is the same shape as the reporting, which is the point of the
hierarchy being a fact in the schema rather than a view assembled per screen.
These tests pin what a node is allowed to claim about the nodes under it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import (
    Tenant,
    ensure_edition,
    login,
    make_chapter,
    make_exercise,
    make_subject,
)

from alppy.models import (
    UNFILED_CHAPTER_KEY,
    Attempt,
    Chapter,
    Competency,
    Sheet,
    Student,
    class_subject,
)
from alppy.models.enums import CurriculumKind, SheetTarget
from alppy.services import class_service

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _competency(
    db: Session, code: str, *, parent: Competency | None = None
) -> Competency:
    row = Competency(
        id=uuid.uuid4(),
        edition_id=ensure_edition(db),
        curriculum=CurriculumKind.PER,
        code=code,
        parent_id=parent.id if parent else None,
        subject_key="mathematics",
        cycle=3,
        labels={"fr": code, "de": code, "en": code},
        description={},
    )
    db.add(row)
    db.flush()
    return row


def _attempt(
    db: Session,
    tenant: Tenant,
    student: Student,
    exercise_id: uuid.UUID,
    *,
    correct: bool,
    days_ago: float = 1.0,
    score: float = 1.0,
) -> None:
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            person_id=student.person_id,
            exercise_id=exercise_id,
            correct=correct,
            score=score,
            difficulty=3,
            answered_at=NOW - timedelta(days=days_ago),
        )
    )
    db.flush()


def _declare(db: Session, tenant: Tenant) -> None:
    class_service.declare_subject(
        db, tenant.scope, tenant.school_class.id, tenant.subject.id
    )
    db.commit()


def test_the_tree_nests_branch_competence_theme(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    area = _competency(db, "MSN 33")
    leaf = _competency(db, "MSN 33.2", parent=area)
    chapter = make_chapter(
        db, tenant, key="linear_equations", competencies=[leaf], primary_competency=leaf
    )
    exercise = make_exercise(db, tenant, statement="2x + 3 = 9", with_competency=False)
    exercise.competencies = [leaf]
    db.flush()
    _attempt(db, tenant, tenant.students[0], exercise.id, correct=True)
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    body = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()

    assert len(body["branches"]) == 1
    branch = body["branches"][0]
    assert branch["subject_id"] == str(tenant.subject.id)

    assert len(branch["competences"]) == 1
    competence = branch["competences"][0]
    # The Competence node is the PARENT of the chapter's primary, not the
    # primary itself.
    assert competence["code"] == "MSN 33"

    assert [t["chapter_id"] for t in competence["themes"]] == [str(chapter.id)]
    assert competence["themes"][0]["mastery"]["band"] == "solid"


def test_a_top_level_primary_is_its_own_competence(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Without the fallback this would render a nameless Competence node."""
    orphan = _competency(db, "MSN 35")  # no parent
    make_chapter(
        db, tenant, key="modelling", competencies=[orphan], primary_competency=orphan
    )
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    body = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()
    competence = body["branches"][0]["competences"][0]
    assert competence["code"] == "MSN 35"
    assert len(competence["themes"]) == 1


def test_unfiled_sheets_are_counted_but_never_rolled_up(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The bucket has to stay findable without becoming a mastery number."""
    area = _competency(db, "MSN 32")
    leaf = _competency(db, "MSN 32.1", parent=area)
    make_chapter(
        db, tenant, key="fractions", competencies=[leaf], primary_competency=leaf
    )
    unfiled = db.execute(
        select(Chapter)
        .where(Chapter.school_id == tenant.school.id)
        .where(Chapter.key == UNFILED_CHAPTER_KEY)
    ).scalar_one_or_none()
    if unfiled is None:
        from alppy.services.chapter_service import ensure_unfiled_chapter

        unfiled = ensure_unfiled_chapter(
            db, school_id=tenant.school.id, subject_id=tenant.subject.id
        )
    db.add(
        Sheet(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            class_id=tenant.school_class.id,
            subject_id=tenant.subject.id,
            chapter_id=unfiled.id,
            title="Révision de juin",
            target=SheetTarget.CLASS,
            language="fr",
            layout_version="v1",
        )
    )
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    branch = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()[
        "branches"
    ][0]

    assert branch["unfiled_sheet_count"] == 1
    # It is not a Theme in the tree...
    themes = [t["key"] for c in branch["competences"] for t in c["themes"]]
    assert UNFILED_CHAPTER_KEY not in themes
    # ...and its sheet contributed nothing to the Branch band.
    assert branch["mastery"]["band"] == "none"


def test_a_theme_reports_the_coverage_behind_its_band(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A band alone would let a Theme read "acquis" on one of three
    competencies. DC-colour-08 one level up: the colour never travels alone.
    """
    area = _competency(db, "MSN 33")
    seen = _competency(db, "MSN 33.1", parent=area)
    unseen_a = _competency(db, "MSN 33.2", parent=area)
    unseen_b = _competency(db, "MSN 33.3", parent=area)
    make_chapter(
        db,
        tenant,
        key="algebra",
        competencies=[seen, unseen_a, unseen_b],
        primary_competency=seen,
    )
    exercise = make_exercise(db, tenant, statement="3(x+1)", with_competency=False)
    exercise.competencies = [seen]
    db.flush()
    for _ in range(4):
        _attempt(db, tenant, tenant.students[0], exercise.id, correct=True)
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    theme = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()[
        "branches"
    ][0]["competences"][0]["themes"][0]

    assert theme["mastery"]["band"] == "solid"
    assert theme["mastery"]["assessed_count"] == 1
    assert theme["mastery"]["child_count"] == 3
    # Never-assessed is not a weakness, so it does not become the weakest band.
    assert theme["mastery"]["weakest_band"] == "solid"


def test_student_id_narrows_the_tree_to_one_child(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    area = _competency(db, "MSN 33")
    leaf = _competency(db, "MSN 33.2", parent=area)
    make_chapter(
        db, tenant, key="equations", competencies=[leaf], primary_competency=leaf
    )
    exercise = make_exercise(db, tenant, statement="x = ?", with_competency=False)
    exercise.competencies = [leaf]
    db.flush()
    strong, weak = tenant.students[0], tenant.students[1]
    for _ in range(4):
        _attempt(db, tenant, strong, exercise.id, correct=True)
    _attempt(db, tenant, weak, exercise.id, correct=False)
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    base = f"/api/v1/classes/{tenant.school_class.id}/tree"
    strong_band = client.get(f"{base}?student_id={strong.id}").json()["branches"][0][
        "competences"
    ][0]["themes"][0]["mastery"]["band"]
    weak_band = client.get(f"{base}?student_id={weak.id}").json()["branches"][0][
        "competences"
    ][0]["themes"][0]["mastery"]["band"]

    assert strong_band == "solid"
    assert weak_band == "fading"


def test_the_tree_never_reads_the_bareme(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`Attempt.score` is the teacher's marking scheme; `Attempt.correct` is
    what the model reads. A barème must not be able to rewrite what the model
    believes a child knows.
    """
    area = _competency(db, "MSN 34")
    leaf = _competency(db, "MSN 34.1", parent=area)
    make_chapter(db, tenant, key="areas", competencies=[leaf], primary_competency=leaf)
    exercise = make_exercise(db, tenant, statement="aire ?", with_competency=False)
    exercise.competencies = [leaf]
    db.flush()
    # Every answer wrong, but generously scored — even a bonus above 1.
    for _ in range(4):
        _attempt(db, tenant, tenant.students[0], exercise.id, correct=False, score=5.0)
    _declare(db, tenant)
    login(client, tenant.teacher.email)

    theme = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()[
        "branches"
    ][0]["competences"][0]["themes"][0]
    assert theme["mastery"]["band"] == "fading"
    assert theme["mastery"]["score"] == 0.0


def test_subject_id_narrows_to_one_branch(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _declare(db, tenant)
    login(client, tenant.teacher.email)
    body = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/tree?subject_id={uuid.uuid4()}"
    ).json()
    assert body["branches"] == []


def test_a_colleagues_class_has_no_tree(
    client: TestClient, tenant: Tenant, colleague: Tenant, db: Session
) -> None:
    login(client, colleague.teacher.email)
    response = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree")
    assert response.status_code == 404


# --- the Branch level itself ---------------------------------------------
def test_branches_are_declared_not_derived_from_sheets(
    tenant: Tenant, db: Session
) -> None:
    """The old read was `SELECT DISTINCT sheet.subject_id`, which meant a new
    class had no Branch level until somebody built it a sheet.

    Asserted on a SECOND branch: the fixture's own subject is declared when
    the teacher is assigned to it, which is the state 0021's backfill leaves
    behind, so a fresh one is what shows the declaration doing the work.
    """
    german = make_subject(db, tenant.school, "german")
    before = class_service.declared_subject_ids_for_class(
        db, tenant.scope, tenant.school_class.id
    )
    assert german.id not in before

    class_service.declare_subject(db, tenant.scope, tenant.school_class.id, german.id)
    db.flush()

    # No Sheet row exists at all, and the Branch is still there.
    assert db.execute(select(Sheet)).all() == []
    assert class_service.declared_subject_ids_for_class(
        db, tenant.scope, tenant.school_class.id
    ) == [*before, german.id]


def test_declaring_a_branch_twice_changes_nothing(tenant: Tenant, db: Session) -> None:
    for _ in range(3):
        class_service.declare_subject(
            db, tenant.scope, tenant.school_class.id, tenant.subject.id
        )
    db.flush()
    rows = db.execute(select(class_subject)).all()
    assert len(rows) == 1
    assert rows[0].position == 0


def test_branches_keep_the_order_the_class_met_them(
    tenant: Tenant, db: Session
) -> None:
    """First-use order, not alphabetical — that is what the column means."""
    from alppy.models import Subject

    german = Subject(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        key="german",
        labels={"fr": "Allemand"},
    )
    db.add(german)
    db.flush()

    class_service.declare_subject(
        db, tenant.scope, tenant.school_class.id, tenant.subject.id
    )
    class_service.declare_subject(db, tenant.scope, tenant.school_class.id, german.id)
    db.flush()

    assert class_service.declared_subject_ids_for_class(
        db, tenant.scope, tenant.school_class.id
    ) == [tenant.subject.id, german.id]
    positions = sorted(r.position for r in db.execute(select(class_subject)).all())
    assert positions == [0, 1]


def test_a_colleague_cannot_read_another_classs_branches(
    tenant: Tenant, colleague: Tenant, db: Session
) -> None:
    class_service.declare_subject(
        db, tenant.scope, tenant.school_class.id, tenant.subject.id
    )
    db.flush()
    assert (
        class_service.declared_subject_ids_for_class(
            db, colleague.scope, tenant.school_class.id
        )
        == []
    )


def test_two_chapters_cannot_share_a_key_within_a_subject(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`uq_chapter_key` is what makes the `unfiled` bucket a singleton.

    Without it two concurrent first-ever sheets in a subject each create a
    bucket, and that subject's unfiled sheets split silently between them. The
    endpoint names the clash rather than letting it surface as a 500.
    """
    login(client, tenant.teacher.email)
    body = {
        "subject_id": str(tenant.subject.id),
        "key": "fractions",
        "labels": {"fr": "Fractions", "de": "Brüche", "en": "Fractions"},
        "competency_ids": [],
    }
    assert client.post("/api/v1/chapters", json=body).status_code == 201
    clash = client.post("/api/v1/chapters", json=body)
    assert clash.status_code == 409
    assert "fractions" in clash.text
