"""Editing the nouns a school owns — and, mostly, refusing to.

Every route here writes to something only the seed could create before, so the
interesting half is never the happy path: it is what the endpoint refuses, and
whether it says why in terms a teacher could act on.

Three rules run through the file, each with a failure worth picturing:

* **Renaming is not re-identifying.** A label may always change; a `key`, a
  `code` or a `uid` may not once paper has been printed from it.
* **Deleting is not unenrolling, and it is not a cascade.** Every delete either
  refuses with a count of what still points at it, or is a no-op. Exactly one
  operation may destroy evidence, and it asks for the pupil's UID typed back.
* **The corpus is shared for reading, not for deleting** (D11 vs D77).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, assign_branch, login, make_subject

from alppy.models import UNFILED_CHAPTER_KEY, Attempt, Chapter, Student, Subject


# --------------------------------------------------------------------------
# Subject — the Branch, and the constraint a create endpoint made reachable
# --------------------------------------------------------------------------
def test_a_new_branch_arrives_with_its_unfiled_bucket(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`Sheet.chapter_id` is NOT NULL and falls back to `unfiled` (D60).

    A Branch created without one would 422 the first sheet built in it — the
    teacher's very next action.
    """
    login(client, tenant.teacher.email)
    response = client.post(
        "/api/v1/subjects", json={"key": "german", "labels": {"fr": "Allemand"}}
    )
    assert response.status_code == 201
    subject_id = uuid.UUID(response.json()["id"])

    bucket = db.execute(
        Chapter.__table__.select()
        .where(Chapter.subject_id == subject_id)
        .where(Chapter.key == UNFILED_CHAPTER_KEY)
    ).one_or_none()
    assert bucket is not None
    # It is excluded from the tree by primary_competency_id IS NULL, never by
    # its key — a school may relabel it.
    assert bucket.primary_competency_id is None


def test_two_branches_cannot_share_a_key(
    client: TestClient, tenant: Tenant
) -> None:
    """`uq_subject_key`, reported as a conflict rather than a 500.

    `Competency.subject_key` matches `Subject.key` BY STRING, so two subjects
    keyed the same in one school split the curriculum silently — half the
    competencies resolving to each.
    """
    login(client, tenant.teacher.email)
    first = client.post("/api/v1/subjects", json={"key": "german", "labels": {}})
    assert first.status_code == 201
    again = client.post("/api/v1/subjects", json={"key": "  GERMAN ", "labels": {}})
    assert again.status_code == 409, "case and whitespace must not smuggle a duplicate past"


def test_a_branch_can_be_renamed_but_not_re_keyed(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/subjects/{tenant.subject.id}",
        json={"labels": {"fr": "Maths", "de": "Mathe", "en": "Maths"}},
    )
    assert response.status_code == 200
    assert response.json()["labels"]["fr"] == "Maths"
    # The key is not in SubjectUpdate at all: it is what the curriculum joins on.
    assert response.json()["key"] == db.get(Subject, tenant.subject.id).key


# --------------------------------------------------------------------------
# Class — the code is printed on paper
# --------------------------------------------------------------------------
def test_a_class_label_is_always_editable(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/classes/{tenant.school_class.id}", json={"label": "Groupe du matin"}
    )
    assert response.status_code == 200
    assert response.json()["label"] == "Groupe du matin"


def test_a_class_code_is_refused_once_pupils_exist(
    client: TestClient, tenant: Tenant
) -> None:
    """`Student.uid` (`7B_15`) was minted from the code and is PRINTED.

    The pile on the desk does not update, and the detector reads what is on
    the paper (I-platform-09). The refusal carries the count so the teacher
    can see why.
    """
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/classes/{tenant.school_class.id}", json={"code": "8C"}
    )
    assert response.status_code == 409
    assert int(response.json()["error"]["details"]["student_count"]) == len(tenant.students)


def test_a_brand_new_class_can_have_its_code_corrected(
    client: TestClient, tenant: Tenant
) -> None:
    """A typo made at creation must be fixable.

    A class with no roster has minted no UIDs, so nothing is printed yet and
    the refusal above would only be pedantry.
    """
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/classes", json={"code": "9z", "label": None})
    assert created.status_code == 201
    fixed = client.patch(f"/api/v1/classes/{created.json()['id']}", json={"code": "9Z"})
    assert fixed.status_code == 200
    assert fixed.json()["code"] == "9Z"


def test_a_code_correction_still_refuses_a_collision(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/classes", json={"code": "9Z", "label": None})
    response = client.patch(
        f"/api/v1/classes/{created.json()['id']}", json={"code": tenant.school_class.code}
    )
    assert response.status_code == 409


# --------------------------------------------------------------------------
# School
# --------------------------------------------------------------------------
def test_the_school_can_be_renamed(client: TestClient, tenant: Tenant) -> None:
    login(client, tenant.teacher.email)
    response = client.patch(
        "/api/v1/schools/me", json={"name": "CO des Alpes", "canton": "vs"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "CO des Alpes"
    assert response.json()["canton"] == "VS"


def test_the_curriculum_cannot_be_switched_from_the_settings_screen(
    client: TestClient, tenant: Tenant
) -> None:
    """`default_curriculum` is resolved into every chapter at seed time (D56).

    Changing it later would leave every Theme hanging from the other
    curriculum's node — a silent mis-filing of the whole tree from a field
    that looks like a preference. It is not in `SchoolUpdate`, so it is
    ignored rather than applied.
    """
    login(client, tenant.teacher.email)
    before = client.get("/api/v1/auth/me").json()["schools"]
    kind = next(s["default_curriculum"] for s in before if s["id"] == str(tenant.school.id))
    response = client.patch(
        "/api/v1/schools/me", json={"name": "CO des Alpes", "default_curriculum": "LP21"}
    )
    assert response.status_code == 200
    assert response.json()["default_curriculum"] == kind


# --------------------------------------------------------------------------
# Student — names are ordinary, identifiers are not, deletion is evidence
# --------------------------------------------------------------------------
def test_a_pupils_name_can_be_corrected_without_touching_their_identifier(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    student = tenant.students[0]
    uid, number = student.uid, student.number
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/students/{student.id}", json={"last_name": "Favre-Rossier"}
    )
    assert response.status_code == 200
    assert response.json()["last_name"] == "Favre-Rossier"
    db.refresh(student)
    assert (student.uid, student.number) == (uid, number)


def test_deleting_a_pupil_needs_their_identifier_typed_back(
    client: TestClient, tenant: Tenant
) -> None:
    """Not a boolean flag.

    A caller firing `?confirm=true` at the wrong row deletes the wrong child.
    The UID is the one string that is unambiguous and already in front of the
    teacher, on the paper.
    """
    student = tenant.students[0]
    login(client, tenant.teacher.email)
    wrong = client.delete(f"/api/v1/students/{student.id}?confirm=nonsense")
    assert wrong.status_code == 422
    assert wrong.json()["error"]["details"]["expected"] == student.uid


def test_deleting_a_pupil_destroys_their_evidence(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """The only operation in Alppy allowed to do this (`data-model.md` §6).

    What this level can prove is that the endpoint really removes the pupil.
    That their `Attempt`s go with them is a CASCADE, and the suite runs on
    SQLite, which does not enforce foreign keys (D18) — asserting it here
    would pass on an empty promise. It is asserted against real Postgres in
    `test_schema_constraints.py` instead.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")  # noqa: F405
    student = tenant.students[0]
    sheet, _scan, detection = make_paper_trail(db, tenant, exercise, student)  # noqa: F405
    # `make_paper_trail` builds the scan chain; an Attempt is what CONFIRMING
    # a pile writes, and it is the row that carries a child's evidence.
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            student_id=student.id,
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            detection_id=detection.id,
            correct=True,
            score=1.0,
            difficulty=3,
            answered_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    db.commit()
    assert db.execute(
        Attempt.__table__.select().where(Attempt.student_id == student.id)
    ).all()

    login(client, tenant.teacher.email)
    response = client.delete(f"/api/v1/students/{student.id}?confirm={student.uid}")
    assert response.status_code == 204

    # The handler committed on its own session; drop this one's identity map
    # or `db.get` answers from cache and the assertion proves nothing.
    db.expire_all()
    assert db.execute(
        Student.__table__.select().where(Student.id == student.id)
    ).all() == []


def test_a_co_teacher_cannot_delete_another_teachers_pupil(
    client: TestClient, db: Session, tenant: Tenant, colleague: Tenant
) -> None:
    """Reading a child and erasing one are not the same permission.

    A subject teacher who co-teaches the class reads the pupil (D73 is
    class-grained about identity) but deletion follows the HOME class, which
    is what says whose pupil this is (D69).
    """
    history = make_subject(db, tenant.school, "history")
    assign_branch(db, tenant.school_class, colleague.teacher, history, position=1)
    db.commit()
    student = tenant.students[0]

    login(client, colleague.teacher.email)
    assert client.get(f"/api/v1/students/{student.id}/mastery").status_code == 200
    response = client.delete(f"/api/v1/students/{student.id}?confirm={student.uid}")
    assert response.status_code == 404
    db.expire_all()
    assert db.execute(
        Student.__table__.select().where(Student.id == student.id)
    ).all() != []


# --------------------------------------------------------------------------
# Theme (Chapter) — and the honest shape of "a competence I teach"
# --------------------------------------------------------------------------
def test_a_theme_credits_the_competencies_the_teacher_chooses(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """A teacher cannot create a `Competency` — it is national reference data
    shared by every school (D11). What they choose is which ones their Theme
    CREDITS (`chapter_competency`), and that is what this endpoint edits.

    Not `primary_competency_id`: that is where the Theme SITS in the tree,
    resolved per school from `School.default_curriculum` (D56), and moving it
    would move the Theme to another Branch of the navigation.
    """
    chapter = make_chapter(  # noqa: F405
        db, tenant, key="fractions", competencies=[tenant.competency]
    )
    db.commit()
    primary_before = chapter.primary_competency_id

    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/chapters/{chapter.id}",
        json={"labels": {"fr": "Fractions et décimaux"}, "competency_ids": []},
    )
    assert response.status_code == 200
    assert response.json()["labels"]["fr"] == "Fractions et décimaux"
    db.expire_all()
    db.refresh(chapter)
    assert chapter.competencies == []
    assert chapter.primary_competency_id == primary_before, "the tree must not move"


def test_a_theme_holding_sheets_cannot_be_deleted(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`Sheet.chapter_id` is RESTRICT, so the refusal exists either way.

    Without this it arrives as an IntegrityError 500 — true, and unreadable.
    The count is what lets a teacher decide whether to refile them.
    """
    exercise = make_exercise(db, tenant, statement="1/2 + 1/4 ?")  # noqa: F405
    db.commit()
    login(client, tenant.teacher.email)
    created = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    chapter_id = created.json()["chapter_id"]

    response = client.delete(f"/api/v1/chapters/{chapter_id}")
    # The sheet went to `unfiled`, which is undeletable for its own reason —
    # either refusal is correct, and neither may be a 500.
    assert response.status_code == 409


def test_the_unfiled_bucket_cannot_be_deleted(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Recognised by `primary_competency_id IS NULL`, never by its key.

    A school may relabel the bucket, and a rename must not make it deletable —
    the same two-test rule `tree_service` follows when excluding it.
    """
    login(client, tenant.teacher.email)
    response = client.delete(f"/api/v1/chapters/{tenant.unfiled_chapter_id}")
    assert response.status_code == 409


def test_a_theme_cannot_be_deleted_by_someone_who_does_not_teach_the_branch(
    client: TestClient, db: Session, tenant: Tenant, colleague: Tenant
) -> None:
    """The corpus is shared for READING, not for deleting (D11 vs D77).

    Set in a branch only the host teaches: the colleague fixture shares the
    host's subject (they take it in their own class), so a chapter there would
    prove nothing about the rule.
    """
    german = make_subject(db, tenant.school, "german")
    assign_branch(db, tenant.school_class, tenant.teacher, german, position=1)
    chapter = make_chapter(  # noqa: F405
        db, tenant, key="decimaux", competencies=[tenant.competency]
    )
    chapter.subject_id = german.id
    db.commit()

    # The colleague can SEE it — chapters are school-wide on purpose.
    login(client, colleague.teacher.email)
    listed = client.get(f"/api/v1/chapters?subject_id={german.id}")
    assert listed.status_code == 200
    assert str(chapter.id) in {row["id"] for row in listed.json()}
    # Destroying it is where isolation reaches in.
    assert client.delete(f"/api/v1/chapters/{chapter.id}").status_code == 422

    # And the teacher who does hold that branch may.
    login(client, tenant.teacher.email)
    assert client.delete(f"/api/v1/chapters/{chapter.id}").status_code == 204


# --------------------------------------------------------------------------
# Textbook (Source)
# --------------------------------------------------------------------------
def _make_source(db: Session, tenant: Tenant, filename: str = "algebre.pdf") -> object:
    from alppy.models import Source
    from alppy.models.enums import JobStatus

    row = Source(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        subject_id=tenant.subject.id,
        uploaded_by_id=tenant.teacher.id,
        filename=filename,
        storage_key=f"sources/{tenant.school.id}/{uuid.uuid4()}/{filename}",
        content_type="application/pdf",
        size_bytes=1024,
        sha256="0" * 64,
        status=JobStatus.SUCCEEDED,
    )
    db.add(row)
    db.flush()
    return row


def test_a_textbook_gets_a_name_of_its_own(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`filename` is what was uploaded ("scan 3 (copy).pdf") — provenance, not
    a name. Before `title` it was the only thing the shelf could show."""
    source = _make_source(db, tenant)
    db.commit()
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/sources/{source.id}",  # type: ignore[attr-defined]
        json={"title": "Algèbre 9e — Éditions LEP"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Algèbre 9e — Éditions LEP"
    assert response.json()["filename"] == "algebre.pdf", "the upload's own name stays"


def test_a_textbook_with_exercises_cannot_be_deleted(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`Exercise.source_id` is SET NULL, so this would otherwise SUCCEED.

    That is the danger: not a crash, but a silent strip of provenance from
    every exercise cut from the book — the one thing `ExerciseOrigin.TEXTBOOK`
    exists to assert. A count is the honest refusal.
    """
    source = _make_source(db, tenant)
    exercise = make_exercise(db, tenant, statement="Résoudre 2x + 3 = 7")  # noqa: F405
    exercise.source_id = source.id  # type: ignore[attr-defined]
    db.commit()

    login(client, tenant.teacher.email)
    response = client.delete(f"/api/v1/sources/{source.id}")  # type: ignore[attr-defined]
    assert response.status_code == 409
    assert response.json()["error"]["details"]["exercise_count"] == "1"


def test_a_textbook_nothing_cites_can_be_deleted(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    source = _make_source(db, tenant, filename="unused.pdf")
    db.commit()
    login(client, tenant.teacher.email)
    assert client.delete(f"/api/v1/sources/{source.id}").status_code == 204  # type: ignore[attr-defined]


def test_a_discarded_exercise_does_not_hold_a_textbook_hostage(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """`discarded_at` means the teacher already threw the exercise away.

    Counting it would make a book undeletable forever because of items nobody
    can reach — the count has to mean what the shelf shows.
    """
    from datetime import UTC, datetime

    source = _make_source(db, tenant, filename="old.pdf")
    exercise = make_exercise(db, tenant, statement="Ancien")  # noqa: F405
    exercise.source_id = source.id  # type: ignore[attr-defined]
    exercise.discarded_at = datetime.now(UTC)
    db.commit()

    login(client, tenant.teacher.email)
    assert client.delete(f"/api/v1/sources/{source.id}").status_code == 204  # type: ignore[attr-defined]


# --------------------------------------------------------------------------
# A second establishment, created from the product
# --------------------------------------------------------------------------
def test_creating_a_school_joins_it_but_does_not_switch_to_it(
    client: TestClient, tenant: Tenant
) -> None:
    """Two decisions, kept apart.

    Creating a school and acting for it are different intentions, and doing
    both at once would move the tenant out from under a teacher who was only
    setting things up. The creator is a MEMBER immediately, though — a school
    nobody can act for is not a school, and `get_membership` would refuse the
    very next request.
    """
    login(client, tenant.teacher.email)
    created = client.post(
        "/api/v1/schools",
        json={"name": "Oberstufe Chur", "canton": "gr", "default_curriculum": "LP21"},
    )
    assert created.status_code == 201
    assert created.json()["canton"] == "GR"
    new_id = created.json()["id"]

    me = client.get("/api/v1/auth/me").json()
    assert new_id in {s["id"] for s in me["schools"]}, "the creator joined it"
    assert me["school_id"] == str(tenant.school.id), "but the session did not move"

    # And it is real: switching lands there.
    assert client.post(f"/api/v1/auth/school/{new_id}").status_code == 200


def test_a_colleague_can_be_added_to_a_staffroom_you_work_in(
    client: TestClient, tenant: Tenant, colleague: Tenant
) -> None:
    login(client, tenant.teacher.email)
    created = client.post("/api/v1/schools", json={"name": "Oberstufe Chur"})
    new_id = created.json()["id"]

    added = client.post(f"/api/v1/schools/{new_id}/teachers/{colleague.teacher.id}")
    assert added.status_code == 201
    assert str(colleague.teacher.id) in {row["id"] for row in added.json()}

    # The colleague can now act for it.
    login(client, colleague.teacher.email)
    assert client.post(f"/api/v1/auth/school/{new_id}").status_code == 200


def test_you_cannot_add_a_colleague_to_a_school_you_do_not_work_in(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """Missing, not forbidden — so this cannot be used to discover which
    school ids are real."""
    login(client, tenant.teacher.email)
    response = client.post(
        f"/api/v1/schools/{other_tenant.school.id}/teachers/{tenant.teacher.id}"
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# The shelf's bibliographic facts
# --------------------------------------------------------------------------
def test_a_textbook_carries_the_facts_that_identify_it(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """Publisher, ISBN and URL are for a HUMAN deciding whether two shelves
    hold the same book. Nothing parses them, which is why the ISBN is stored
    as typed rather than normalised."""
    source = _make_source(db, tenant)
    db.commit()
    login(client, tenant.teacher.email)
    response = client.patch(
        f"/api/v1/sources/{source.id}",  # type: ignore[attr-defined]
        json={
            "title": "Algèbre 9e",
            "publisher": "Éditions LEP",
            "isbn": "978-2-606-01234-5",
            "url": "https://example.ch/algebre",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["publisher"] == "Éditions LEP"
    assert body["isbn"] == "978-2-606-01234-5", "stored as typed, not normalised"
    assert body["url"] == "https://example.ch/algebre"
