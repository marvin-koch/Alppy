"""Demo seed — everything a reviewer needs on a clean machine.

`run_seed` is what `docker compose up` calls. It is **idempotent**: running it
on every boot is safe, and re-running it never duplicates a student or an
attempt.

The point of the seed is not to fill tables, it is to make the product
demonstrable and honest. So the mastery matrix is not written down: 18 invented
students each get an ability profile, three weeks of lessons are simulated from
it, and the bands come out of the real model in `alppy.mastery`. If the model
changes, the demo changes with it — which is exactly how the retention
half-life bug in `docs/mastery-model.md` was found.

No real student names, and no copyrighted textbook content: the corpus in
`seed/data/` is self-authored.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.core.security import hash_password
from alppy.core.uid import format_uid
from alppy.db.validity import today
from alppy.models import (
    Attempt,
    Chapter,
    Class,
    Exercise,
    Person,
    School,
    SchoolYear,
    Student,
    Subject,
    Teacher,
    class_student,
)
from alppy.models.enums import CurriculumKind, Locale
from alppy.seed import staging as staging_data
from alppy.seed.demo import (
    COLLEAGUE_CLASS_CODE,
    COLLEAGUE_EMAIL,
    COLLEAGUE_PASSWORD,
    COLLEAGUE_ROSTER,
    DEMO_CLASS_CODE,
    DEMO_ROSTER,
    DEMO_SCHOOL,
    DEMO_SCHOOL_2,
    DEMO_SECOND_CLASS_CODE,
    DEMO_SECOND_ROSTER,
    DEMO_TEACHER_EMAIL,
    DEMO_TEACHER_PASSWORD,
    lesson_moments,
    simulate_attempts,
)
from alppy.seed.loader import load_demo_corpus, load_reference_data
from alppy.services import class_service
from alppy.services.mastery_service import recompute_for_people

log = get_logger(__name__)


def run_seed(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Create (or reuse) the demo school, class, corpus and three weeks of work."""
    moment = now or datetime.now(UTC)

    school = _get_or_create_school(db)
    teacher = _get_or_create_teacher(db, school)
    # A second staffroom, so `docker compose up` can actually demonstrate the
    # switch. Camille works at both; nothing else is seeded there, which is
    # the honest picture of a teacher who has just been given a second post.
    second = _get_or_create_second_school(db)
    class_service.join_school(db, teacher.id, second.id)
    year = _get_or_create_year(db, school, moment)

    reference = load_reference_data(db, school_id=school.id)
    subject = db.execute(
        select(Subject).where(Subject.school_id == school.id).where(Subject.key == "mathematics")
    ).scalar_one()
    corpus = load_demo_corpus(db, school_id=school.id, subject_id=subject.id)

    school_class = _get_or_create_class(db, school, year, teacher)
    students = _get_or_create_students(db, school, year, school_class)

    # A second class for the same teacher, so the class switcher has somewhere
    # to switch to, and a second subject so the subject switcher does too.
    second_class = _get_or_create_class(
        db, school, year, teacher, code=DEMO_SECOND_CLASS_CODE, label="Mathématiques — 9e"
    )
    _get_or_create_students(db, school, year, second_class, roster=DEMO_SECOND_ROSTER)
    sciences = _get_or_create_subject(
        db,
        school,
        key="sciences",
        labels={"fr": "Sciences de la nature", "de": "Naturwissenschaften", "en": "Sciences"},
    )

    # A colleague in the same school. Their class must never show up on the
    # demo teacher's home screen — that is the point of them.
    colleague = _get_or_create_colleague(db, school)
    colleague_class = _get_or_create_class(
        db, school, year, colleague, code=COLLEAGUE_CLASS_CODE, label="Classe de Beatrice"
    )
    _get_or_create_students(db, school, year, colleague_class, roster=COLLEAGUE_ROSTER)
    db.flush()

    created = _simulate_history(db, school, students, moment)
    db.flush()

    if created:
        # One recompute per lesson date, oldest first, then one for today. A
        # single recompute at the end leaves exactly one snapshot per cell, and
        # the profile curve — which needs at least two points to be a curve —
        # never renders. Each pass sees only the attempts that existed on that
        # date, so the series shows the class actually learning.
        person_ids = [s.person_id for s in students.values()]
        for lesson_moment in lesson_moments(moment):
            recompute_for_people(db, school.id, person_ids, now=lesson_moment)
        recompute_for_people(db, school.id, person_ids, now=moment)

    db.commit()

    summary = {
        "school": school.name,
        "teacher": teacher.email,
        "class": school_class.code,
        "classes": [school_class.code, second_class.code],
        "colleague": colleague.email,
        "colleague_class": colleague_class.code,
        "subjects": [subject.key, sciences.key],
        "students": len(students),
        "competencies": len(reference.competency_ids),
        "chapters": len(reference.chapter_ids),
        "exercises": corpus.exercises_created + corpus.exercises_updated,
        "attempts_created": created,
    }
    log.info("seed.done", **summary)
    return summary


# --------------------------------------------------------------------------
# Each helper reuses what is already there, so the whole seed is idempotent.
# --------------------------------------------------------------------------
def _get_or_create_school(db: Session) -> School:
    school = db.execute(select(School).where(School.name == DEMO_SCHOOL)).scalar_one_or_none()
    if school is None:
        school = School(
            id=uuid.uuid4(),
            name=DEMO_SCHOOL,
            canton="VD",
            default_curriculum=CurriculumKind.PER,
        )
        db.add(school)
        db.flush()
    return school


def _get_or_create_second_school(db: Session) -> School:
    """The other school Camille teaches at.

    Deliberately a different canton and curriculum: LP21 rather than PER is
    what makes the pair worth having in a demo — it is the case D56 exists
    for, where the same chapter is filed under each canton's own code.
    """
    school = db.execute(
        select(School).where(School.name == DEMO_SCHOOL_2)
    ).scalar_one_or_none()
    if school is None:
        school = School(
            id=uuid.uuid4(),
            name=DEMO_SCHOOL_2,
            canton="GR",
            default_curriculum=CurriculumKind.LP21,
        )
        db.add(school)
        db.flush()
    return school


def _get_or_create_teacher(db: Session, school: School) -> Teacher:
    teacher = db.execute(
        select(Teacher).where(Teacher.email == DEMO_TEACHER_EMAIL)
    ).scalar_one_or_none()
    if teacher is None:
        teacher = Teacher(
            id=uuid.uuid4(),
            home_school_id=school.id,
            email=DEMO_TEACHER_EMAIL,
            password_hash=hash_password(DEMO_TEACHER_PASSWORD),
            first_name="Camille",
            last_name="Rochat",
            locale=Locale.FR,
        )
        db.add(teacher)
        db.flush()
    class_service.join_school(db, teacher.id, school.id)
    return teacher


def _get_or_create_year(db: Session, school: School, now: datetime) -> SchoolYear:
    # The Swiss school year runs August to July.
    start_year = now.year if now.month >= 8 else now.year - 1
    label = f"{start_year}/{str(start_year + 1)[2:]}"
    year = db.execute(
        select(SchoolYear)
        .where(SchoolYear.school_id == school.id)
        .where(SchoolYear.label == label)
    ).scalar_one_or_none()
    if year is None:
        year = SchoolYear(
            id=uuid.uuid4(),
            school_id=school.id,
            label=label,
            starts_on=date(start_year, 8, 15),
            ends_on=date(start_year + 1, 7, 5),
            is_current=True,
        )
        db.add(year)
        db.flush()
    return year


def _get_or_create_class(
    db: Session,
    school: School,
    year: SchoolYear,
    teacher: Teacher,
    *,
    code: str = DEMO_CLASS_CODE,
    label: str = "Mathématiques — cycle 3",
) -> Class:
    school_class = db.execute(
        select(Class)
        .where(Class.school_id == school.id)
        .where(Class.school_year_id == year.id)
        .where(Class.code == code)
    ).scalar_one_or_none()
    if school_class is None:
        school_class = Class(
            id=uuid.uuid4(),
            school_id=school.id,
            school_year_id=year.id,
            head_teacher_id=teacher.id,
            code=code,
            label=label,
        )
        db.add(school_class)
        db.flush()
    return school_class


def _get_or_create_subject(
    db: Session, school: School, *, key: str, labels: dict[str, str]
) -> Subject:
    subject = db.execute(
        select(Subject).where(Subject.school_id == school.id).where(Subject.key == key)
    ).scalar_one_or_none()
    if subject is None:
        subject = Subject(id=uuid.uuid4(), school_id=school.id, key=key, labels=labels)
        db.add(subject)
        db.flush()
    return subject


def _get_or_create_colleague(db: Session, school: School) -> Teacher:
    """Another teacher in the same staffroom.

    Not a fixture for a test — a fixture for a *reviewer*: tenancy between
    colleagues cannot be checked on a seed with one teacher in it.
    """
    teacher = db.execute(
        select(Teacher).where(Teacher.email == COLLEAGUE_EMAIL)
    ).scalar_one_or_none()
    if teacher is None:
        teacher = Teacher(
            id=uuid.uuid4(),
            home_school_id=school.id,
            email=COLLEAGUE_EMAIL,
            password_hash=hash_password(COLLEAGUE_PASSWORD),
            first_name="Beatrice",
            last_name="Blanc",
            locale=Locale.FR,
        )
        db.add(teacher)
        db.flush()
    class_service.join_school(db, teacher.id, school.id)
    return teacher


def _get_or_create_students(
    db: Session,
    school: School,
    year: SchoolYear,
    school_class: Class,
    *,
    roster: list[tuple[str, str]] | None = None,
) -> dict[str, Student]:
    """Keyed by first name, which is how the simulated history refers to them."""
    existing = {
        s.first_name: s
        for s in db.scalars(
            select(Student)
            .where(Student.school_id == school.id)
            .where(Student.home_class_id == school_class.id)
        )
    }
    for number, (first, last) in enumerate(roster or DEMO_ROSTER, start=1):
        if first in existing:
            continue
        person = Person(
            id=uuid.uuid4(),
            school_id=school.id,
            first_name=first,
            last_name=last,
        )
        db.add(person)
        student = Student(
            id=uuid.uuid4(),
            school_id=school.id,
            person_id=person.id,
            home_class_id=school_class.id,
            school_year_id=year.id,
            # Built with format_uid so the demo carries the same zero-padded
            # shape the roster endpoint produces, and the printed grid aligns.
            uid=format_uid(school_class.code, number),
            number=number,
            first_name=first,
            last_name=last,
        )
        db.add(student)
        existing[first] = student
    # Flush before seating: the join row carries a real FK to student.id.
    db.flush()
    # `index_where` since 0027: the plain (class_id, student_id) unique
    # constraint is gone, and the index that replaced it is PARTIAL. Postgres
    # matches an ON CONFLICT target to a partial index only when the predicate
    # is repeated here, so without it a re-run of the seed raises instead of
    # doing nothing.
    db.execute(
        pg_insert(class_student)
        .values(
            [
                {
                    "class_id": school_class.id,
                    "student_id": s.id,
                    "valid_from": today(),
                }
                for s in existing.values()
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["class_id", "student_id"],
            index_where=text("valid_to IS NULL"),
        )
    )
    return existing


def _simulate_history(
    db: Session,
    school: School,
    students: dict[str, Student],
    now: datetime,
    *,
    roster: list[tuple[str, str]] | None = None,
    profiles: dict[str, Any] | None = None,
) -> int:
    """Three weeks of lessons, replayed into `Attempt` rows.

    Skipped entirely if these students already have attempts: the seed must be
    safe to run on every container start, and a second pass would double every
    student's evidence and quietly shift the whole matrix.

    The check is per **student**, not per school. It was per school, which is
    right when a school holds one taught class and wrong the moment it holds
    three: the first class seeded would make every later one look already done,
    and staging would come up with two thirds of its classes empty.
    """
    ids = [s.person_id for s in students.values()]
    already = db.execute(
        select(Attempt.id)
        .where(Attempt.school_id == school.id)
        .where(Attempt.person_id.in_(ids))
        .limit(1)
    ).scalar_one_or_none()
    if already is not None:
        return 0

    exercises_by_chapter: dict[str, list[tuple[str, int]]] = {}
    chapter_keys = {
        c.id: c.key
        for c in db.scalars(select(Chapter).where(Chapter.school_id == school.id))
    }
    by_id: dict[str, Exercise] = {}
    for exercise in db.scalars(
        select(Exercise).where(Exercise.school_id == school.id)
    ):
        key = chapter_keys.get(exercise.chapter_id) if exercise.chapter_id else None
        if key is None:
            continue
        by_id[str(exercise.id)] = exercise
        exercises_by_chapter.setdefault(key, []).append(
            (str(exercise.id), exercise.difficulty)
        )

    if not exercises_by_chapter:
        log.warning("seed.no_exercises_for_history")
        return 0

    rows = simulate_attempts(
        now=now,
        exercises_by_chapter=exercises_by_chapter,
        roster=roster,
        profiles=profiles,
    )
    created = 0
    for row in rows:
        student = students.get(str(row["student_first_name"]))
        target = by_id.get(str(row["exercise_key"]))
        if student is None or target is None:
            continue
        answered_at = row["answered_at"]
        assert isinstance(answered_at, datetime)
        db.add(
            Attempt(
                id=uuid.uuid4(),
                school_id=school.id,
                person_id=student.person_id,
                exercise_id=target.id,
                correct=bool(row["correct"]),
                score=1.0 if row["correct"] else 0.0,
                difficulty=int(str(row["difficulty"])),
                answered_at=answered_at,
            )
        )
        created += 1
    return created


def run_staging_seed(
    db: Session, *, password: str, now: datetime | None = None
) -> dict[str, Any]:
    """The larger synthetic dataset a staging deployment runs on.

    Same machinery as `run_seed`, different scale and a different reason. The
    demo seed exists so a reviewer on a clean laptop sees a plausible classroom;
    this exists so nobody ever needs a real one. An empty staging deployment is
    the condition under which somebody imports a real roster "just to test
    with", so staging is given six classes of twenty across both curricula, plus
    one class with a roster and no history — enough that a class list scrolls, a
    batch render takes real time, and every empty state is reachable.

    Every name comes from `alppy.seed.staging`'s closed corpus, which is what
    lets `test_staging_seed.py` assert that a staging database contains nobody
    real. The passwords come from the caller (`ALPPY_SEED_TEACHER_PASSWORD`),
    never from the constants published in this repository.

    Idempotent, like `run_seed`: every helper reuses what is already there.
    """
    moment = now or datetime.now(UTC)
    summary: dict[str, Any] = {"schools": [], "classes": [], "students": 0, "attempts": 0}

    for school_name, (canton, curriculum) in staging_data.STAGING_SCHOOLS.items():
        school = db.execute(
            select(School).where(School.name == school_name)
        ).scalar_one_or_none()
        if school is None:
            school = School(
                id=uuid.uuid4(),
                name=school_name,
                canton=canton,
                default_curriculum=curriculum,
            )
            db.add(school)
            db.flush()

        # One teacher per school, at a domain that can never resolve.
        email = f"teacher.{canton.lower()}@{staging_data.STAGING_TEACHER_DOMAIN}"
        teacher = db.execute(
            select(Teacher).where(Teacher.email == email)
        ).scalar_one_or_none()
        if teacher is None:
            teacher = Teacher(
                id=uuid.uuid4(),
                home_school_id=school.id,
                email=email,
                password_hash=hash_password(password),
                first_name="Staging",
                last_name=canton,
                locale=Locale.FR if curriculum is CurriculumKind.PER else Locale.DE,
            )
            db.add(teacher)
            db.flush()
        class_service.join_school(db, teacher.id, school.id)

        year = _get_or_create_year(db, school, moment)
        load_reference_data(db, school_id=school.id)
        subject = db.execute(
            select(Subject)
            .where(Subject.school_id == school.id)
            .where(Subject.key == "mathematics")
        ).scalar_one()
        load_demo_corpus(db, school_id=school.id, subject_id=subject.id)

        for entry in staging_data.STAGING_CLASSES:
            if entry.school != school_name:
                continue
            school_class = _get_or_create_class(
                db, school, year, teacher, code=entry.code, label=f"Mathématiques — {entry.code}"
            )
            roster = staging_data.roster_for(entry.code, entry.size)
            students = _get_or_create_students(
                db, school, year, school_class, roster=roster
            )
            db.flush()
            summary["classes"].append(entry.code)
            summary["students"] += len(students)

            if not entry.taught:
                # The point of this class is that it has nothing. Simulating a
                # history here would remove the only route to every "class with
                # students but nothing taught yet" empty state.
                continue

            created = _simulate_history(
                db,
                school,
                students,
                moment,
                roster=roster,
                profiles=staging_data.profiles_for(entry.code, roster),
            )
            db.flush()
            summary["attempts"] += created
            if created:
                ids = [s.person_id for s in students.values()]
                for lesson_moment in lesson_moments(moment):
                    recompute_for_people(db, school.id, ids, now=lesson_moment)
                recompute_for_people(db, school.id, ids, now=moment)

        summary["schools"].append(school_name)

    db.commit()
    log.info("seed.staging.done", **summary)
    return summary


__all__ = ["run_seed", "run_staging_seed"]
