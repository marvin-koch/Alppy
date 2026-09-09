"""The mastery matrix and the student profile."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import (
    Tenant,
    login,
    make_chapter,
    make_exercise,
    make_paper_trail,
)

from alppy.models import Attempt, Competency, MasterySnapshot
from alppy.models.enums import CurriculumKind
from alppy.services.mastery_service import recompute_for_students


def _second_competency(db: Session) -> Competency:
    competency = Competency(
        id=uuid.uuid4(),
        curriculum=CurriculumKind.PER,
        code="MSN.13",
        parent_id=None,
        subject_key="mathematics",
        cycle=3,
        labels={"fr": "Proportionnalite"},
        description={},
    )
    db.add(competency)
    db.flush()
    return competency


def _seed_history(db: Session, tenant: Tenant) -> Competency:
    """One strong competency and one failing one, for the same student."""
    strong = make_exercise(db, tenant, statement="strong")
    weak_competency = _second_competency(db)
    weak_exercise = make_exercise(db, tenant, statement="weak", with_competency=False)
    weak_exercise.competencies = [weak_competency]
    db.flush()

    student = tenant.students[0]
    recently = datetime.now(UTC) - timedelta(hours=2)
    for _ in range(4):
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=strong.id,
                correct=True,
                score=1.0,
                difficulty=3,
                answered_at=recently,
            )
        )
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=weak_exercise.id,
                correct=False,
                score=0.0,
                difficulty=3,
                answered_at=recently,
            )
        )
    db.commit()
    recompute_for_students(db, tenant.school.id, [student.id])
    db.commit()
    return weak_competency


def test_matrix_has_a_cell_for_every_student_and_competency(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)

    matrix = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery").json()
    assert len(matrix["students"]) == 3
    assert len(matrix["competencies"]) == 2
    assert len(matrix["cells"]) == 6

    student_id = str(tenant.students[0].id)
    bands = {
        c["competency_id"]: c["band"] for c in matrix["cells"] if c["student_id"] == student_id
    }
    assert sorted(bands.values()) == ["fading", "solid"]

    # A student who has sat nothing is "none", never a zero score.
    untouched = [c for c in matrix["cells"] if c["student_id"] == str(tenant.students[1].id)]
    assert {c["band"] for c in untouched} == {"none"}
    assert all(c["attempts_count"] == 0 for c in untouched)


def test_matrix_can_be_narrowed_to_one_subject(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)
    matrix = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?subject_id={tenant.subject.id}"
    ).json()
    assert len(matrix["competencies"]) == 2

    other = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?subject_id={uuid.uuid4()}"
    ).json()
    assert other["competencies"] == []
    assert other["cells"] == []


def test_student_profile_separates_strengths_from_gaps(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    weak_competency = _seed_history(db, tenant)
    login(client, tenant.teacher.email)

    profile = client.get(f"/api/v1/students/{tenant.students[0].id}/mastery").json()
    assert profile["student"]["uid"] == "7B_01"
    assert [s["band"] for s in profile["strengths"]] == ["solid"]
    assert [g["competency"]["code"] for g in profile["gaps"]] == [weak_competency.code]
    assert len(profile["all_competencies"]) == 2
    assert 0.0 < profile["overall_score"] < 1.0

    history = profile["all_competencies"][0]["history"]
    assert len(history) == 1
    assert history[0]["band"] in {"solid", "fading"}


def test_recompute_is_idempotent_within_a_day(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    before = db.execute(select(MasterySnapshot)).scalars().all()
    recompute_for_students(db, tenant.school.id, [tenant.students[0].id])
    db.commit()
    after = db.execute(select(MasterySnapshot)).scalars().all()
    assert len(after) == len(before) == 2


def test_a_later_day_appends_a_point_rather_than_overwriting(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """MasterySnapshot is a time series, and the curve depends on it.

    The same-day case above asserts the *update* branch; nothing asserted the
    append branch, so the seed could ship one snapshot per cell — and did,
    which left the profile curve permanently unrendered.
    """
    _seed_history(db, tenant)
    student = tenant.students[0]
    day_one = datetime.now(UTC)

    recompute_for_students(db, tenant.school.id, [student.id], now=day_one)
    db.commit()
    first = db.execute(
        select(MasterySnapshot).where(MasterySnapshot.student_id == student.id)
    ).scalars().all()
    scores_before = sorted(round(s.score, 6) for s in first)

    recompute_for_students(
        db, tenant.school.id, [student.id], now=day_one + timedelta(days=1)
    )
    db.commit()
    second = db.execute(
        select(MasterySnapshot).where(MasterySnapshot.student_id == student.id)
    ).scalars().all()

    assert len(second) == 2 * len(first), "a later day must append, not overwrite"
    days = {s.computed_at.date() for s in second}
    assert len(days) == 2
    # The earlier values are still there — that is what "retains" means.
    kept = sorted(
        round(s.score, 6)
        for s in second
        if s.computed_at.date() == min(days)
    )
    assert kept == scores_before

    login(client, tenant.teacher.email)
    profile = client.get(f"/api/v1/students/{student.id}/mastery")
    assert profile.status_code == 200, profile.text
    histories = [len(c["history"]) for c in profile.json()["all_competencies"]]
    assert all(h == 2 for h in histories), "the profile curve needs both points"


def test_a_recompute_only_sees_the_evidence_that_existed_at_the_time(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """Backfilling a history must not stamp today's number on an old row.

    Without the ``as_of`` cut-off every backfilled point is computed from the
    full attempt list, so the curve is flat and says nothing.
    """
    _seed_history(db, tenant)
    student = tenant.students[0]
    long_before = datetime.now(UTC) - timedelta(days=30)

    written = recompute_for_students(
        db, tenant.school.id, [student.id], now=long_before
    )
    db.commit()
    # Every attempt in the fixture is two hours old, so 30 days ago this
    # student had been assessed on nothing at all.
    assert written == 0
    assert (
        db.execute(
            select(MasterySnapshot)
            .where(MasterySnapshot.student_id == student.id)
            .where(MasterySnapshot.computed_at < long_before + timedelta(hours=1))
        ).scalars().all()
        == []
    )


def test_profile_of_a_student_with_no_attempts_is_empty_not_an_error(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    profile = client.get(f"/api/v1/students/{tenant.students[2].id}/mastery").json()
    assert profile["overall_score"] == 0.0
    assert profile["strengths"] == []
    assert profile["gaps"] == []
    assert profile["sheets_taken"] == 0


def test_home_reports_students_needing_attention(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    login(client, tenant.teacher.email)
    summary = client.get("/api/v1/home").json()["classes"][0]
    assert summary["students_needing_attention"] == 1
    assert summary["band_counts"]["solid"] == 1
    assert summary["band_counts"]["fading"] == 1


# --- the drill-down behind a cell ----------------------------------------
def test_a_cell_drills_down_to_the_attempts_behind_it(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A band is an argument; this is the evidence for it.

    Clicking a cell used to land on the student profile with the competency
    thrown away and no attempt list anywhere in the product.
    """
    _seed_history(db, tenant)
    student = tenant.students[0]
    login(client, tenant.teacher.email)

    response = client.get(
        f"/api/v1/students/{student.id}/competencies/{tenant.competency.id}/attempts"
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["student"]["uid"] == student.uid
    assert body["competency"]["code"] == tenant.competency.code
    assert body["band"] == "solid"
    # Four correct answers on the strong competency, newest first.
    assert len(body["attempts"]) == 4
    assert all(a["correct"] is True for a in body["attempts"])
    assert [a["statement"] for a in body["attempts"]] == ["strong"] * 4
    stamps = [a["answered_at"] for a in body["attempts"]]
    assert stamps == sorted(stamps, reverse=True)
    # The provenance fields exist even when the fixture has no paper behind it.
    assert set(body["attempts"][0]) >= {"sheet_id", "sheet_title", "scan_id", "corrected"}


def test_the_drill_down_carries_provenance_back_to_the_sheet_and_the_scan(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """"Where did this mark come from" is the first question a teacher asks."""
    exercise = make_exercise(db, tenant, statement="from a real sheet")
    student = tenant.students[0]
    sheet, scan, detection = make_paper_trail(db, tenant, exercise, student)
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            student_id=student.id,
            exercise_id=exercise.id,
            sheet_id=sheet.id,
            detection_id=detection.id,
            correct=False,
            score=0.0,
            difficulty=3,
            answered_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    db.commit()
    login(client, tenant.teacher.email)

    body = client.get(
        f"/api/v1/students/{student.id}/competencies/{tenant.competency.id}/attempts"
    ).json()
    row = next(a for a in body["attempts"] if a["statement"] == "from a real sheet")
    assert row["sheet_id"] == str(sheet.id)
    assert row["sheet_title"] == sheet.title
    assert row["scan_id"] == str(scan.id)
    assert row["corrected"] is True  # the teacher overrode the scanner
    assert row["origin"] == "textbook"


def test_the_drill_down_refuses_another_schools_student(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    foreign = other_tenant.students[0].id
    response = client.get(
        f"/api/v1/students/{foreign}/competencies/{other_tenant.competency.id}/attempts"
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_the_drill_down_needs_a_session(client: TestClient, tenant: Tenant) -> None:
    response = client.get(
        f"/api/v1/students/{tenant.students[0].id}"
        f"/competencies/{tenant.competency.id}/attempts"
    )
    assert response.status_code == 401


# --- filtering and sorting -----------------------------------------------
def test_the_matrix_narrows_to_one_chapter(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    weak_competency = _seed_history(db, tenant)
    chapter = make_chapter(db, tenant, key="fractions", competencies=[weak_competency])
    login(client, tenant.teacher.email)

    unfiltered = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery").json()
    assert len(unfiltered["competencies"]) == 2

    narrowed = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?chapter_id={chapter.id}"
    ).json()
    assert [c["code"] for c in narrowed["competencies"]] == [weak_competency.code]
    assert len(narrowed["cells"]) == len(narrowed["students"])

    # An unknown chapter narrows to nothing rather than leaking that it is
    # unknown, and rather than silently falling back to the whole matrix.
    empty = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?chapter_id={uuid.uuid4()}"
    ).json()
    assert empty["competencies"] == []
    assert empty["cells"] == []


def test_a_chapter_from_another_school_narrows_to_nothing(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    _seed_history(db, tenant)
    foreign_chapter = make_chapter(
        db, other_tenant, key="fractions", competencies=[other_tenant.competency]
    )
    login(client, tenant.teacher.email)
    body = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?chapter_id={foreign_chapter.id}"
    ).json()
    assert body["competencies"] == []


def test_the_matrix_can_be_sorted_weakest_first(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The order a teacher actually reads the grid in."""
    _seed_history(db, tenant)
    # students[0] has one failing competency; students[1] has nothing at all.
    strong_student = tenant.students[1]
    exercise = make_exercise(db, tenant, statement="all correct")
    for _ in range(4):
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=strong_student.id,
                exercise_id=exercise.id,
                correct=True,
                score=1.0,
                difficulty=3,
                answered_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
    db.commit()
    login(client, tenant.teacher.email)

    roster = client.get(f"/api/v1/classes/{tenant.school_class.id}/mastery").json()
    assert [s["number"] for s in roster["students"]] == [1, 2, 3]

    weakest = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?sort=weakest"
    ).json()
    order = [s["uid"] for s in weakest["students"]]
    assert order[0] == tenant.students[0].uid, "the failing student comes first"
    # A student with nothing assessed is not a weakness — they sort last, or
    # the list stops being "who needs help".
    assert order[-1] == tenant.students[2].uid

    # The cells must travel with their rows, not stay in roster order.
    first_row = weakest["cells"][: len(weakest["competencies"])]
    assert {c["student_id"] for c in first_row} == {str(tenant.students[0].id)}


def test_an_unknown_sort_is_rejected_rather_than_ignored(
    client: TestClient, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    response = client.get(
        f"/api/v1/classes/{tenant.school_class.id}/mastery?sort=alphabetical"
    )
    assert response.status_code == 422


# --- the sheets a student sat --------------------------------------------
def test_the_profile_lists_the_sheets_the_student_sat(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """`sheets_taken` was a bare integer and was never rendered anywhere."""
    student = tenant.students[0]
    # Two items on one sheet: an attempt is unique per (student, exercise,
    # sheet), which is the F2 rule that stops a re-scan doubling the record.
    first = make_exercise(db, tenant, statement="item one")
    second = make_exercise(db, tenant, statement="item two")
    sheet, scan, detection = make_paper_trail(db, tenant, first, student)
    for exercise, correct in ((first, True), (second, False)):
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                student_id=student.id,
                exercise_id=exercise.id,
                sheet_id=sheet.id,
                detection_id=detection.id,
                correct=correct,
                score=1.0 if correct else 0.0,
                difficulty=3,
                answered_at=datetime.now(UTC) - timedelta(hours=3),
            )
        )
    db.commit()
    login(client, tenant.teacher.email)

    profile = client.get(f"/api/v1/students/{student.id}/mastery")
    assert profile.status_code == 200, profile.text
    sheets = profile.json()["sheets"]
    assert len(sheets) == 1
    assert sheets[0]["sheet_id"] == str(sheet.id)
    assert sheets[0]["title"] == sheet.title
    assert sheets[0]["attempts_count"] == 2
    assert sheets[0]["correct_count"] == 1
    assert sheets[0]["scan_id"] == str(scan.id)
    assert profile.json()["sheets_taken"] == 1


# --------------------------------------------------------------------------
# The branch-level curve cache (D78, I-mastery-12)
# --------------------------------------------------------------------------
def test_recomputing_stamps_a_branch_point_for_the_curve(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """A cache for history, written by recompute and by nothing else.

    The competency-level rows answer "how is this child doing"; a curve needs
    points, and history is the one question recomputation cannot answer —
    yesterday's number cannot be derived from today's attempts, because the
    score decays.
    """
    from alppy.models import MasteryBranchSnapshot

    _seed_history(db, tenant)
    rows = db.execute(
        select(MasteryBranchSnapshot).where(
            MasteryBranchSnapshot.student_id == tenant.students[0].id
        )
    ).scalars().all()

    assert len(rows) == 1, "one point per (student, branch, day)"
    assert rows[0].subject_id == tenant.subject.id
    assert 0.0 <= rows[0].score <= 1.0
    # It carries its own coverage, because a band over one assessed competency
    # and one over three are different claims (DC-content-07).
    assert rows[0].child_count == 2
    assert rows[0].assessed_child_count == 2


def test_a_second_recompute_the_same_day_corrects_the_point_rather_than_doubling(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """One row per day, like `MasterySnapshot`.

    Confirming a second pile this afternoon must correct this morning's point,
    not draw the curve twice — a doubled point is a curve that jumps for a
    reason nobody can see.
    """
    from alppy.models import MasteryBranchSnapshot

    _seed_history(db, tenant)
    recompute_for_students(db, tenant.school.id, [tenant.students[0].id])
    db.commit()

    rows = db.execute(
        select(MasteryBranchSnapshot).where(
            MasteryBranchSnapshot.student_id == tenant.students[0].id
        )
    ).scalars().all()
    assert len(rows) == 1


def test_no_read_path_answers_a_band_from_the_cache(
    client: TestClient, tenant: Tenant, db: Session
) -> None:
    """The contract, asserted rather than trusted to a docstring.

    The cache is deliberately falsified here — a perfect score stamped on a
    child who has been failing. Every read must ignore it and recompute, or a
    matrix opened on Friday shows Monday's numbers (`data-model.md` §4).
    """
    from alppy.models import MasteryBranchSnapshot
    from alppy.models.enums import MasteryBand

    _seed_history(db, tenant)
    row = db.execute(
        select(MasteryBranchSnapshot).where(
            MasteryBranchSnapshot.student_id == tenant.students[0].id
        )
    ).scalars().one()
    row.score = 1.0
    row.band = MasteryBand.SOLID
    db.commit()

    login(client, tenant.teacher.email)
    tree = client.get(f"/api/v1/classes/{tenant.school_class.id}/tree").json()
    branch = tree["branches"][0]
    assert branch["mastery"]["band"] != "solid", (
        "the tree recomputed instead of reading the poisoned cache"
    )
