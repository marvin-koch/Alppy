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

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.core.security import hash_password
from alppy.core.uid import format_uid
from alppy.models import (
    Attempt,
    Chapter,
    Class,
    Exercise,
    School,
    SchoolYear,
    Student,
    Subject,
    Teacher,
)
from alppy.models.enums import CurriculumKind, Locale
from alppy.seed.demo import (
    COLLEAGUE_CLASS_CODE,
    COLLEAGUE_EMAIL,
    COLLEAGUE_PASSWORD,
    COLLEAGUE_ROSTER,
    DEMO_CLASS_CODE,
    DEMO_ROSTER,
    DEMO_SCHOOL,
    DEMO_SECOND_CLASS_CODE,
    DEMO_SECOND_ROSTER,
    DEMO_TEACHER_EMAIL,
    DEMO_TEACHER_PASSWORD,
    lesson_moments,
    simulate_attempts,
)
from alppy.seed.loader import load_demo_corpus, load_reference_data
from alppy.services.mastery_service import recompute_for_students

log = get_logger(__name__)


def run_seed(db: Session, *, now: datetime | None = None) -> dict[str, Any]:
    """Create (or reuse) the demo school, class, corpus and three weeks of work."""
    moment = now or datetime.now(UTC)

    school = _get_or_create_school(db)
    teacher = _get_or_create_teacher(db, school)
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
        student_ids = [s.id for s in students.values()]
        for lesson_moment in lesson_moments(moment):
            recompute_for_students(db, school.id, student_ids, now=lesson_moment)
        recompute_for_students(db, school.id, student_ids, now=moment)

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


def _get_or_create_teacher(db: Session, school: School) -> Teacher:
    teacher = db.execute(
        select(Teacher).where(Teacher.email == DEMO_TEACHER_EMAIL)
    ).scalar_one_or_none()
    if teacher is None:
        teacher = Teacher(
            id=uuid.uuid4(),
            school_id=school.id,
            email=DEMO_TEACHER_EMAIL,
            password_hash=hash_password(DEMO_TEACHER_PASSWORD),
            first_name="Camille",
            last_name="Rochat",
            locale=Locale.FR,
        )
        db.add(teacher)
        db.flush()
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
            teacher_id=teacher.id,
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
            school_id=school.id,
            email=COLLEAGUE_EMAIL,
            password_hash=hash_password(COLLEAGUE_PASSWORD),
            first_name="Beatrice",
            last_name="Blanc",
            locale=Locale.FR,
        )
        db.add(teacher)
        db.flush()
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
            .where(Student.class_id == school_class.id)
        )
    }
    for number, (first, last) in enumerate(roster or DEMO_ROSTER, start=1):
        if first in existing:
            continue
        student = Student(
            id=uuid.uuid4(),
            school_id=school.id,
            class_id=school_class.id,
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
    return existing


def _simulate_history(
    db: Session, school: School, students: dict[str, Student], now: datetime
) -> int:
    """Three weeks of lessons, replayed into `Attempt` rows.

    Skipped entirely if attempts already exist: the seed must be safe to run on
    every container start, and a second pass would double every student's
    evidence and quietly shift the whole matrix.
    """
    already = db.execute(
        select(Attempt.id).where(Attempt.school_id == school.id).limit(1)
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

    rows = simulate_attempts(now=now, exercises_by_chapter=exercises_by_chapter)
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
                student_id=student.id,
                exercise_id=target.id,
                correct=bool(row["correct"]),
                score=1.0 if row["correct"] else 0.0,
                difficulty=int(str(row["difficulty"])),
                answered_at=answered_at,
            )
        )
        created += 1
    return created


__all__ = ["run_seed"]
