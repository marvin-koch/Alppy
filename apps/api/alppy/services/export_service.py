"""What this establishment holds about one pupil, gathered into one document.

A parent may ask, and a school leaving Alppy has to be able to take it with
them. Before this the only route out of the product was ``delete_student``,
which is a poor answer to "what do you have on my child" — it answers
"nothing, now".

Reads across every year. The durable identity is ``Person`` and ``Student`` is
one year's enrolment record (0028), so a pupil who repeated a year has two
enrolments and one continuous record of evidence behind them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.models import (
    Attempt,
    Class,
    Competency,
    MisconceptionNote,
    Person,
    SchoolYear,
    Sheet,
    Student,
    class_student,
    exercise_competency,
)
from alppy.schemas import (
    ClassExportOut,
    ExportAttempt,
    ExportEnrolment,
    ExportNote,
    StudentExportOut,
)


def student_export(db: Session, school_id: uuid.UUID, person_id: uuid.UUID) -> StudentExportOut:
    """One pupil's whole record.

    Tenant-filtered on every read even though row-level security is underneath:
    the service-layer filter does not change because the database grew a
    backstop, and a document that leaked one row across a school boundary would
    leak it into a file somebody emails.
    """
    person = db.execute(
        select(Person).where(Person.id == person_id).where(Person.school_id == school_id)
    ).scalar_one()

    enrolments = _enrolments(db, school_id, person_id)
    attempts = _attempts(db, school_id, person_id)
    notes = _notes(db, school_id, person_id)

    return StudentExportOut(
        generated_at=datetime.now(UTC),
        person_id=person.id,
        first_name=person.first_name,
        last_name=person.last_name,
        anonymised_at=person.anonymised_at,
        enrolments=enrolments,
        attempts=attempts,
        notes=notes,
    )


def class_export(
    db: Session, school_id: uuid.UUID, klass: Class, students: list[Student]
) -> ClassExportOut:
    """A whole class, as one document (D36).

    `docs/privacy.md` §4 has promised this since it was written — "a school can
    request a full export of one class ... the mechanism a school uses to take
    its data with it" — and only the per-PUPIL export existed. Which meant a
    school of four hundred children exercised its portability right twenty-four
    pupils at a time, by hand, and a procurement question about leaving had no
    answer that was not embarrassing.

    **The roster as it stands, not everyone who ever sat here**, and the choice
    matters. `class_student` is an interval, so "who is in 7B" depends on when
    you ask; a teacher who arrived in March has no standing over a pupil who
    left in October, and that gate — the overlap rule in
    `ever_shared_student_ids` — is deliberately narrower than "ever enrolled".
    Rather than invent a third access rule inside an export, this exports
    exactly the pupils the caller may already act on. A pupil who has left is
    still exportable individually through the per-pupil route, under the gate
    that governs them.

    Each pupil is rendered by `student_export`, so the class document and the
    single-pupil document cannot drift: one shape, one place. Mastery snapshots
    stay out for the reason they stay out of the pupil export — they are
    recomputed from the attempts below, and a decaying score is a photograph of
    a calculation, not an independent fact about a child.
    """
    # `Class` carries `school_year_id` and no relationship, so the label is
    # fetched rather than traversed. It is in the document because a class code
    # alone (`7B`) does not identify a class across years, and an export that
    # cannot say which year it describes is an export somebody has to date by
    # hand.
    year = db.get(SchoolYear, klass.school_year_id)
    return ClassExportOut(
        generated_at=datetime.now(UTC),
        class_id=klass.id,
        class_code=klass.code,
        school_year=year.label if year else None,
        student_count=len(students),
        students=[student_export(db, school_id, s.person_id) for s in students],
    )


def _enrolments(
    db: Session, school_id: uuid.UUID, person_id: uuid.UUID
) -> list[ExportEnrolment]:
    """Every year's record, and within a year every class they sat in.

    ``home_class_id`` is the class that MINTED the uid; the ``class_student``
    rows are where they actually sat, which is not the same set (D69). Both
    matter to somebody reading this back, so both are here — one row per
    membership, flagged.
    """
    rows = db.execute(
        select(Student, Class, SchoolYear, class_student.c.valid_from, class_student.c.valid_to)
        .join(class_student, class_student.c.student_id == Student.id, isouter=True)
        .join(Class, Class.id == class_student.c.class_id, isouter=True)
        .join(SchoolYear, SchoolYear.id == Student.school_year_id, isouter=True)
        .where(Student.person_id == person_id)
        .where(Student.school_id == school_id)
        .order_by(Student.created_at.asc())
    ).all()

    out: list[ExportEnrolment] = []
    for student, school_class, year, valid_from, valid_to in rows:
        out.append(
            ExportEnrolment(
                student_id=student.id,
                uid=student.uid,
                number=student.number,
                class_id=school_class.id if school_class else None,
                class_code=school_class.code if school_class else None,
                school_year=year.label if year else None,
                is_home_class=bool(school_class and school_class.id == student.home_class_id),
                valid_from=valid_from,
                valid_to=valid_to,
            )
        )
    return out


def _attempts(db: Session, school_id: uuid.UUID, person_id: uuid.UUID) -> list[ExportAttempt]:
    rows = db.execute(
        select(Attempt, Sheet.title)
        .join(Sheet, Sheet.id == Attempt.sheet_id, isouter=True)
        .where(Attempt.person_id == person_id)
        .where(Attempt.school_id == school_id)
        .order_by(Attempt.answered_at.asc())
    ).all()
    if not rows:
        return []

    # The codes rather than the ids: a document read outside Alppy cannot
    # resolve a uuid, and `MSN 33.2` is the thing a parent or another school
    # can actually look up.
    exercise_ids = {attempt.exercise_id for attempt, _title in rows}
    codes: dict[uuid.UUID, list[str]] = {}
    for exercise_id, code in db.execute(
        select(exercise_competency.c.exercise_id, Competency.code)
        .join(Competency, Competency.id == exercise_competency.c.competency_id)
        .where(exercise_competency.c.exercise_id.in_(exercise_ids))
    ).all():
        codes.setdefault(exercise_id, []).append(code)

    return [
        ExportAttempt(
            answered_at=attempt.answered_at,
            exercise_id=attempt.exercise_id,
            competency_codes=sorted(codes.get(attempt.exercise_id, [])),
            correct=attempt.correct,
            score=attempt.score,
            difficulty=attempt.difficulty,
            sheet_id=attempt.sheet_id,
            sheet_title=title,
        )
        for attempt, title in rows
    ]


def _notes(db: Session, school_id: uuid.UUID, person_id: uuid.UUID) -> list[ExportNote]:
    """Discarded notes are excluded: a note the teacher threw away is not part
    of the record, and re-surfacing it in an export is the opposite of what
    throwing it away meant."""
    rows = db.execute(
        select(MisconceptionNote)
        .where(MisconceptionNote.person_id == person_id)
        .where(MisconceptionNote.school_id == school_id)
        .where(MisconceptionNote.discarded_at.is_(None))
        .order_by(MisconceptionNote.created_at.asc())
    ).scalars()
    return [
        ExportNote(
            created_at=note.created_at,
            subject_id=note.subject_id,
            language=note.language,
            notes=list(note.notes or []),
            based_on_sheet_id=note.based_on_sheet_id,
            approved_at=note.approved_at,
        )
        for note in rows
    ]


__all__ = ["student_export"]
