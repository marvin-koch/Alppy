"""Generating feedback for a whole class, and reading it back.

`test_feedback.py` covers one student at a time — grounding, the PII gate, the
approval stamp. What it does not cover is the batch the worker actually runs
(`generate_for_sheet`) or the read path the review screen uses
(`latest_for_students`), which between them were most of the uncovered lines in
`feedback_service`.

The rule that matters here is the same one as everywhere else generated content
is involved, and it is stricter for a note than for an exercise: an unreviewed
generated exercise is a bad question a teacher can spot on the page, while an
unreviewed generated note is a claim about how one named child thinks, printed
and handed to that child.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise, make_paper_trail

from alppy.ai.base import ChatRequest, ChatResponse
from alppy.ai.client import AiClient
from alppy.models import Attempt, MisconceptionNote, Student
from alppy.services import feedback_service

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


class _Provider:
    """Returns two notes and records every request it was given."""

    name = "stub"
    grounded = True

    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def complete(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            text='{"notes": ["La multiplication passe avant l addition.", '
            '"Souligne les multiplications d abord."]}',
            model="stub",
        )


def _client(provider: object) -> AiClient:
    client = AiClient()
    client._chat = provider  # type: ignore[assignment]
    return client


def _wrong(
    db: Session,
    tenant: Tenant,
    student: Student,
    *,
    sheet_id: uuid.UUID | None = None,
    statement: str = "Combien font 3 + 4 x 2 ?",
) -> uuid.UUID:
    """One wrongly-answered item for this student, on a shared sheet.

    `make_paper_trail` mints a sheet per call, which is right for a drill-down
    test and wrong here: a class sits the SAME sheet, and the batch is defined
    by that. Passing `sheet_id` files the attempt against the common one.
    """
    exercise = make_exercise(db, tenant, statement=statement, answer_index=1)
    sheet, _scan, detection = make_paper_trail(db, tenant, exercise, student)
    detection.detected_index = 2
    target = sheet_id or sheet.id
    db.add(
        Attempt(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            student_id=student.id,
            exercise_id=exercise.id,
            sheet_id=target,
            detection_id=detection.id,
            correct=False,
            score=0.0,
            difficulty=3,
            answered_at=NOW,
        )
    )
    db.flush()
    return target


# --------------------------------------------------------------------------
# The batch
# --------------------------------------------------------------------------
def test_a_batch_writes_one_note_per_student_with_something_to_say(
    db: Session, tenant: Tenant
) -> None:
    students = tenant.students[:3]
    sheet_id = _wrong(db, tenant, students[0])
    for student in students[1:]:
        _wrong(db, tenant, student, sheet_id=sheet_id)

    provider = _Provider()
    notes = feedback_service.generate_for_sheet(
        db,
        school_id=tenant.school.id,
        source_sheet_id=sheet_id,
        subject_id=tenant.subject.id,
        students=students,
        language="fr",
        ai=_client(provider),
    )
    assert len(notes) == 3
    assert {n.student_id for n in notes} == {s.id for s in students}
    # One call per student: the reason this is a job and not a request handler.
    assert len(provider.requests) == 3


def test_a_batch_skips_the_students_with_a_clean_paper(
    db: Session, tenant: Tenant
) -> None:
    """A class where two of twenty struggled must cost two calls, not twenty,
    and must not hand eighteen children a note about nothing."""
    struggled = tenant.students[0]
    sheet_id = _wrong(db, tenant, struggled)

    provider = _Provider()
    notes = feedback_service.generate_for_sheet(
        db,
        school_id=tenant.school.id,
        source_sheet_id=sheet_id,
        subject_id=tenant.subject.id,
        students=tenant.students,
        language="fr",
        ai=_client(provider),
    )
    assert [n.student_id for n in notes] == [struggled.id]
    assert len(provider.requests) == 1


def test_a_batch_reports_progress_so_the_teacher_sees_it_move(
    db: Session, tenant: Tenant
) -> None:
    """A class of twenty is twenty model calls; a job that reports nothing is a
    spinner for a minute and a half."""
    students = tenant.students[:3]
    sheet_id = _wrong(db, tenant, students[0])
    for student in students[1:]:
        _wrong(db, tenant, student, sheet_id=sheet_id)

    seen: list[tuple[float, str | None]] = []
    feedback_service.generate_for_sheet(
        db,
        school_id=tenant.school.id,
        source_sheet_id=sheet_id,
        subject_id=tenant.subject.id,
        students=students,
        language="fr",
        ai=_client(_Provider()),
        on_progress=lambda fraction, message: seen.append((fraction, message)),
    )
    assert [f for f, _m in seen] == [1 / 3, 2 / 3, 1.0]
    assert seen[-1][1] == "3 / 3"


def test_a_batch_of_nobody_is_not_a_division_by_zero(
    db: Session, tenant: Tenant
) -> None:
    """An empty class is a real state — a sheet printed before the roster was
    imported — and `total` is a denominator."""
    exercise = make_exercise(db, tenant, statement="x", answer_index=1)
    sheet, _scan, _detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    notes = feedback_service.generate_for_sheet(
        db,
        school_id=tenant.school.id,
        source_sheet_id=sheet.id,
        subject_id=tenant.subject.id,
        students=[],
        language="fr",
        ai=_client(_Provider()),
    )
    assert notes == []


def test_a_classmates_name_never_reaches_the_provider(
    db: Session, tenant: Tenant
) -> None:
    """No student name reaches a model provider (CLAUDE.md, docs/privacy.md).

    The batch is where this is easiest to get wrong: the scrubber is given the
    roster, and a batch that passed one student's name at a time would let a
    prompt mentioning a CLASSMATE through — which is the case that matters,
    because that is the child who is not even the subject of the note. Here the
    exercise statement itself carries a classmate's name, the way a word problem
    written round the class does.
    """
    author, classmate = tenant.students[0], tenant.students[1]
    sheet_id = _wrong(
        db,
        tenant,
        author,
        statement=f"{classmate.first_name} {classmate.last_name} achète 3 stylos à 4 francs.",
    )

    provider = _Provider()
    feedback_service.generate_for_sheet(
        db,
        school_id=tenant.school.id,
        source_sheet_id=sheet_id,
        subject_id=tenant.subject.id,
        students=tenant.students,
        language="fr",
        ai=_client(provider),
    )

    assert provider.requests
    for request in provider.requests:
        sent = f"{request.system}\n{request.user}"
        for student in tenant.students:
            assert student.first_name not in sent
            assert student.last_name not in sent


def test_the_roster_is_ordered_longest_first(db: Session, tenant: Tenant) -> None:
    """A scrubber replacing names by substring has to see "Marie-Claire" before
    "Marie", or it leaves "-Claire" behind and the gate reports a clean prompt."""
    names = feedback_service._roster_names(tenant.students)
    assert names == sorted(names, key=len, reverse=True)


def test_a_student_with_a_blank_name_does_not_produce_an_empty_gate_entry(
    db: Session, tenant: Tenant
) -> None:
    """An empty string in the roster would match everywhere, so the gate would
    refuse every prompt and no feedback could be written at all."""
    student = tenant.students[0]
    student.last_name = "   "
    db.flush()
    assert "" not in feedback_service._roster_names([student])
    assert all(name.strip() for name in feedback_service._roster_names([student]))


# --------------------------------------------------------------------------
# Reading it back
# --------------------------------------------------------------------------
def _note(
    db: Session, tenant: Tenant, student: Student, sheet_id: uuid.UUID, *, created: datetime
) -> MisconceptionNote:
    note = MisconceptionNote(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        student_id=student.id,
        subject_id=tenant.subject.id,
        based_on_sheet_id=sheet_id,
        notes=["une note"],
        language="fr",
        created_at=created,
    )
    db.add(note)
    db.flush()
    return note


def test_the_newest_note_per_student_wins(db: Session, tenant: Tenant) -> None:
    """Regenerating keeps the old row — an `Attempt` may point at it — so the
    read path has to choose, and choosing the older one shows the teacher the
    note they just replaced."""
    student = tenant.students[0]
    sheet_id = uuid.uuid4()
    _note(db, tenant, student, sheet_id, created=NOW - timedelta(days=1))
    newest = _note(db, tenant, student, sheet_id, created=NOW)

    found = feedback_service.latest_for_students(
        db,
        school_id=tenant.school.id,
        student_ids=[student.id],
        source_sheet_id=sheet_id,
    )
    assert found[student.id].id == newest.id


def test_a_discarded_note_is_never_returned(db: Session, tenant: Tenant) -> None:
    """A teacher who rejected a claim about a child must not see it again, and
    must certainly not print it."""
    student = tenant.students[0]
    sheet_id = uuid.uuid4()
    note = _note(db, tenant, student, sheet_id, created=NOW)
    note.discarded_at = NOW
    db.flush()

    assert feedback_service.latest_for_students(
        db, school_id=tenant.school.id, student_ids=[student.id], source_sheet_id=sheet_id
    ) == {}


def test_a_discard_reveals_the_note_underneath_it(db: Session, tenant: Tenant) -> None:
    """Not just "the newest, unless discarded" — the newest LIVE one. Otherwise
    discarding a regenerated note leaves the student with nothing rather than
    with the note the teacher had already accepted."""
    student = tenant.students[0]
    sheet_id = uuid.uuid4()
    older = _note(db, tenant, student, sheet_id, created=NOW - timedelta(days=1))
    newer = _note(db, tenant, student, sheet_id, created=NOW)
    newer.discarded_at = NOW
    db.flush()

    found = feedback_service.latest_for_students(
        db, school_id=tenant.school.id, student_ids=[student.id], source_sheet_id=sheet_id
    )
    assert found[student.id].id == older.id


def test_notes_are_scoped_to_the_sheet_they_were_written_about(
    db: Session, tenant: Tenant
) -> None:
    """A misconception note is about one piece of work. Showing last term's
    note next to this week's sheet is a claim about the wrong evidence."""
    student = tenant.students[0]
    this_sheet, other_sheet = uuid.uuid4(), uuid.uuid4()
    _note(db, tenant, student, other_sheet, created=NOW)

    assert feedback_service.latest_for_students(
        db, school_id=tenant.school.id, student_ids=[student.id], source_sheet_id=this_sheet
    ) == {}


def test_another_schools_note_is_not_returned(
    db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    student = tenant.students[0]
    sheet_id = uuid.uuid4()
    _note(db, tenant, student, sheet_id, created=NOW)

    assert feedback_service.latest_for_students(
        db,
        school_id=other_tenant.school.id,
        student_ids=[student.id],
        source_sheet_id=sheet_id,
    ) == {}


def test_asking_about_nobody_asks_the_database_nothing(
    db: Session, tenant: Tenant
) -> None:
    """`IN ()` is a syntax error in some dialects and a full scan in others."""
    assert feedback_service.latest_for_students(
        db, school_id=tenant.school.id, student_ids=[], source_sheet_id=uuid.uuid4()
    ) == {}
