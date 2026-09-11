"""Sheets: build one, edit one, bind it to students.

A sheet has two layers. ``SheetItem`` is the class-level item list a teacher
sees and reorders. ``SheetInstance`` is the printed artefact: one per student,
carrying that student's UID and — for a differentiated batch — its own item
plan. Both are created here so the renderer never has to guess which items a
given child's page should hold.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api import errors
from alppy.api.deps import Scope
from alppy.db.validity import today
from alppy.models import (
    Attempt,
    Chapter,
    Exercise,
    MisconceptionNote,
    Sheet,
    SheetInstance,
    SheetItem,
    Student,
    Subject,
    exercise_competency,
    sheet_source,
)
from alppy.models.enums import EventKind, EventSubject, ExerciseType, SheetTarget
from alppy.schemas import AdaptiveBatchRequest, SheetCreate, SheetItemIn, SheetUpdate
from alppy.services import chapter_service, class_service, event_service
from alppy.services.approval import (
    UnapprovedExerciseError,
    UnapprovedFeedbackError,
    ensure_notes_printable,
    ensure_printable,
)
from alppy.services.class_service import get_class, list_students
from alppy.services.enrollment import taught_here, taught_here_ever
from alppy.sheets.layout import LAYOUT_VERSION


def get_sheet(db: Session, scope: Scope, sheet_id: uuid.UUID) -> Sheet:
    """One sheet in a branch the caller teaches, or 404.

    A sheet carries its class's roster on paper, so it inherits that class's
    ownership rather than only the school boundary (decisions-log D23) — and
    since D73 it is **pair-grained**, not class-grained: a sheet belongs to a
    (class, subject), and a colleague who takes another branch in the same
    class has no business reading it.

    This is also what makes the scan lifecycle safe rather than special-cased.
    Attaching a pile to a sheet resolves it through here, so a teacher can only
    ever attach a sheet they teach — which is why an unmatched pile can never
    flip out of its uploader's list the moment a sheet is chosen.
    """
    # GATE. `on=today()` because this is the resolver every *write* goes
    # through — render, edit, mark-printed, attach a pile, bill a generation.
    # A teacher who has left this (class, branch) may still read what they
    # marked; `get_sheet_for_read` is that door, and it is a different one.
    sheet = db.execute(
        select(Sheet)
        .where(Sheet.id == sheet_id)
        .where(Sheet.school_id == scope.school_id)
        .where(taught_here(Sheet.class_id, Sheet.subject_id, scope, on=today()))
    ).scalar_one_or_none()
    if sheet is None:
        raise errors.not_found("sheet", id=str(sheet_id))
    return sheet


def get_sheet_for_read(db: Session, scope: Scope, sheet_id: uuid.UUID) -> Sheet:
    """One sheet in a branch the caller teaches **or once taught**, or 404.

    The read-side twin of ``get_sheet``, and the reason the pair exists is
    written out under ``enrollment.taught_here_ever`` (D88): a substitute who
    marked eleven sheets between September and February has to be able to
    reconstruct that evidence in June, and the current-only gate 404s all of
    it — including from inside ``sheet_report``, whose own student lookup had
    already been widened for that case and could never reach it.

    Use it for reports and single-sheet reads. Never for a write, and never as
    a shortcut when ``get_sheet`` 404s in a test — that 404 is usually correct.

    ``list_sheets`` deliberately does **not** use this. Browsing is the current
    teacher's working surface, and a group taken over in March would otherwise
    open onto its predecessor's back catalogue. A departed teacher reaches
    these sheets by following a pupil's profile, which is the path the case is
    actually about.
    """
    sheet = db.execute(
        select(Sheet)
        .where(Sheet.id == sheet_id)
        .where(Sheet.school_id == scope.school_id)
        .where(taught_here_ever(Sheet.class_id, Sheet.subject_id, scope))
    ).scalar_one_or_none()
    if sheet is None:
        raise errors.not_found("sheet", id=str(sheet_id))
    return sheet


def list_sheets(
    db: Session,
    scope: Scope,
    *,
    class_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> list[Sheet]:
    stmt = (
        select(Sheet)
        .where(Sheet.school_id == scope.school_id)
        .where(taught_here(Sheet.class_id, Sheet.subject_id, scope, on=today()))
    )
    if class_id is not None:
        stmt = stmt.where(Sheet.class_id == class_id)
    if subject_id is not None:
        stmt = stmt.where(Sheet.subject_id == subject_id)
    if chapter_id is not None:
        stmt = stmt.where(Sheet.chapter_id == chapter_id)
    return list(db.execute(stmt.order_by(Sheet.created_at.desc())).scalars())


def _require_subject(db: Session, school_id: uuid.UUID, subject_id: uuid.UUID) -> Subject:
    subject = db.execute(
        select(Subject).where(Subject.id == subject_id).where(Subject.school_id == school_id)
    ).scalar_one_or_none()
    if subject is None:
        raise errors.not_found("subject", id=str(subject_id))
    return subject


def _resolve_chapter(
    db: Session,
    school_id: uuid.UUID,
    subject_id: uuid.UUID,
    chapter_id: uuid.UUID | None,
) -> Chapter:
    """The Theme this sheet is filed under.

    ``Sheet.chapter_id`` is NOT NULL, but omitting it at the API boundary is a
    real, supported case: the teacher has not filed this yet. That falls back
    to the subject's `unfiled` bucket, which says the true thing, rather than
    to a majority vote over the items' own inferred ``Exercise.chapter_id`` —
    that column is a guess, null on a large minority of real textbook rows,
    and promoting a guess into a filing the teacher never confirmed is what
    ``approved_at`` exists to prevent elsewhere.
    """
    if chapter_id is not None:
        chapter = db.execute(
            select(Chapter)
            .where(Chapter.id == chapter_id)
            .where(Chapter.school_id == school_id)
        ).scalar_one_or_none()
        if chapter is None:
            raise errors.not_found("chapter", id=str(chapter_id))
        if chapter.subject_id != subject_id:
            # A Theme from another Branch is a caller bug, not a valid state:
            # it would put the sheet somewhere the tree can never show it.
            raise errors.unprocessable(
                "chapter belongs to another subject",
                chapter_id=str(chapter_id),
                subject_id=str(subject_id),
            )
        return chapter

    # Created eagerly by migration 0016 and by the reference seed; created here
    # if a subject somehow reached the database without one. A missing
    # structural row must not surface as a 422 on an ordinary "new sheet".
    return chapter_service.ensure_unfiled_chapter(
        db, school_id=school_id, subject_id=subject_id
    )


def _load_exercises(
    db: Session, school_id: uuid.UUID, exercise_ids: list[uuid.UUID]
) -> dict[uuid.UUID, Exercise]:
    if not exercise_ids:
        return {}
    rows = db.execute(
        select(Exercise)
        .where(Exercise.school_id == school_id)
        .where(Exercise.id.in_(exercise_ids))
    ).scalars()
    found = {e.id: e for e in rows}
    missing = [str(i) for i in exercise_ids if i not in found]
    if missing:
        raise errors.not_found("exercise", ids=missing)
    return found


def _validate_positions(items: list[SheetItemIn]) -> None:
    positions = [i.position for i in items]
    if len(set(positions)) != len(positions):
        raise errors.unprocessable("sheet item positions must be unique")


def _replace_items(
    db: Session, school_id: uuid.UUID, sheet: Sheet, items: list[SheetItemIn]
) -> None:
    _validate_positions(items)
    exercises = _load_exercises(db, school_id, [i.exercise_id for i in items])
    for existing in list(sheet.items):
        db.delete(existing)
    db.flush()
    for entry in sorted(items, key=lambda i: i.position):
        db.add(
            SheetItem(
                id=uuid.uuid4(),
                school_id=school_id,
                sheet_id=sheet.id,
                exercise_id=exercises[entry.exercise_id].id,
                position=entry.position,
                statement_override=entry.statement_override,
                answer_box_lines=entry.answer_box_lines,
                answer_box_fill=entry.answer_box_fill,
                expected_answer=(
                    entry.expected_answer
                    if exercises[entry.exercise_id].type is ExerciseType.OPEN
                    else None
                ),
                # Deliberately not type-gated, unlike the wording, the box and
                # the expected answer above. The answer of an MCQ is the
                # bubble, so an expected answer on one is meaningless — but
                # what a bubble is WORTH is not, and neither is what a written
                # item is worth once a verdict grades it.
                points_correct=entry.points_correct,
                points_penalty=entry.points_penalty,
            )
        )
    db.flush()


def _item_plan(items: list[SheetItemIn]) -> list[dict[str, Any]]:
    return [
        {"exercise_id": str(i.exercise_id), "variant_id": None, "position": i.position}
        for i in sorted(items, key=lambda i: i.position)
    ]


def _bind_instances(
    db: Session,
    school_id: uuid.UUID,
    sheet: Sheet,
    students: list[Student],
    plans: dict[uuid.UUID, list[dict[str, Any]]] | None = None,
    group_labels: dict[uuid.UUID, str] | None = None,
    feedback_ids: dict[uuid.UUID, uuid.UUID] | None = None,
) -> None:
    """One printed instance per student, each carrying the student's UID."""
    existing = {i.student_id for i in sheet.instances}
    for student in students:
        if student.id in existing:
            continue
        db.add(
            SheetInstance(
                id=uuid.uuid4(),
                school_id=school_id,
                sheet_id=sheet.id,
                student_id=student.id,
                student_uid=student.uid,
                item_plan=(plans or {}).get(student.id, []),
                group_label=(group_labels or {}).get(student.id),
                feedback_id=(feedback_ids or {}).get(student.id),
            )
        )
    db.flush()


def create_sheet(db: Session, scope: Scope, teacher_id: uuid.UUID, payload: SheetCreate) -> Sheet:
    school_id = scope.school_id
    school_class = get_class(db, scope, payload.class_id)
    _require_subject(db, school_id, payload.subject_id)
    chapter = _resolve_chapter(db, school_id, payload.subject_id, payload.chapter_id)
    # The one place a class and a subject first meet, and therefore the one
    # place that keeps the Branch level of the navigation populated (D57).
    class_service.declare_subject(db, scope, school_class.id, payload.subject_id)

    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=school_id,
        class_id=school_class.id,
        subject_id=payload.subject_id,
        chapter_id=chapter.id,
        created_by_id=teacher_id,
        title=payload.title,
        target=payload.target,
        language=payload.language,
        intent=payload.intent,
        layout_version=LAYOUT_VERSION,
        default_points_correct=payload.default_points_correct,
        default_points_penalty=payload.default_points_penalty,
    )
    db.add(sheet)
    db.flush()

    _replace_items(db, school_id, sheet, payload.items)
    plan = _item_plan(payload.items)
    students = list_students(db, scope, school_class.id)
    _bind_instances(db, school_id, sheet, students, {s.id: plan for s in students})
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.SHEET_CREATED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={"items": len(payload.items), "copies": len(students)},
    )
    db.refresh(sheet)
    return sheet


def update_sheet(
    db: Session, scope: Scope, sheet_id: uuid.UUID, payload: SheetUpdate
) -> Sheet:
    school_id = scope.school_id
    sheet = get_sheet(db, scope, sheet_id)
    if payload.title is not None:
        sheet.title = payload.title
    if payload.chapter_id is not None:
        # Re-filing under a different Theme. Does NOT invalidate the render:
        # the chapter is where the sheet is filed, and it prints nothing.
        sheet.chapter_id = _resolve_chapter(
            db, school_id, sheet.subject_id, payload.chapter_id
        ).id
    # A barème edit changes the paper: every statement prints what it is worth.
    # So it invalidates the render exactly as an item edit does — otherwise the
    # teacher downloads a PDF whose "(1 pt)" disagrees with how it will grade.
    stale = False
    if payload.default_points_correct is not None:
        sheet.default_points_correct = payload.default_points_correct
        stale = True
    if payload.default_points_penalty is not None:
        sheet.default_points_penalty = payload.default_points_penalty
        stale = True
    # Read before the edit clears it: whether this sheet had already been
    # rendered is what turns an ordinary edit into one worth recording.
    was_printed = sheet.rendered_at is not None
    if payload.items is not None:
        _replace_items(db, school_id, sheet, payload.items)
        plan = _item_plan(payload.items)
        for instance in sheet.instances:
            instance.item_plan = plan
        stale = True
    if stale:
        sheet.blank_pdf_key = None
        sheet.answer_key_pdf_key = None
        sheet.rendered_at = None
    if stale and was_printed:
        # An edit to a sheet that has already been printed changes what the
        # grader judges against, on a paper the class has sat (audit 03, B21).
        # The flat staffroom (D85) means any colleague can do it, and until now
        # nothing recorded that anyone had — only that some columns differed
        # from what the PDF said. Not a refusal: re-rendering after a typo is
        # ordinary and the render is invalidated above. Just legible.
        from alppy.services import event_service

        event_service.record(
            db,
            school_id=school_id,
            kind=EventKind.EXERCISE_EDITED,
            subject_type=EventSubject.SHEET,
            subject_id=sheet.id,
            summary=sheet.title,
            actor_id=scope.teacher_id,
            class_id=sheet.class_id,
            subject_area_id=sheet.subject_id,
            detail={"items_replaced": payload.items is not None},
        )
    db.flush()
    db.refresh(sheet)
    return sheet


def people_for_students(
    db: Session, school_id: uuid.UUID, student_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """``{student_id: person_id}``.

    The join 0028 made necessary and deliberately did not hide. A
    ``SheetInstance``, an ``AdaptiveProposal`` and a ``ScanPage`` are all facts
    about one year's paper and keep their ``student_id``; the evidence behind
    them hangs off the person. Every screen showing "this sheet, per pupil"
    needs both halves, and one lookup beats each caller inventing its own.
    """
    ids = list(student_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(Student.id, Student.person_id)
        .where(Student.school_id == school_id)
        .where(Student.id.in_(ids))
    ).all()
    return dict(rows)  # type: ignore[arg-type]  # SQLAlchemy Row pairs


def people_for_instances(
    db: Session, school_id: uuid.UUID, instances: Sequence[SheetInstance]
) -> dict[uuid.UUID, uuid.UUID]:
    """``{student_id: person_id}`` for the copies of one sheet."""
    return people_for_students(db, school_id, [i.student_id for i in instances])


def sheet_coverage(
    db: Session, school_id: uuid.UUID, sheet_id: uuid.UUID
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """The Competences and Themes a sheet's items actually touch.

    Derived, never stored. A `sheet_competency` table would have to be rewritten
    on every item edit and could then disagree with the items it claims to
    describe — two answers to "what does this sheet cover?", one of them stale.
    The items are the only source of truth there is.

    Deliberately NOT the same thing as ``Sheet.chapter_id``. That is the one
    home Theme the teacher STATED (I-sheets-11), and it stays the sheet's
    filing; this is the wider set the items reach into, which is what a sheet
    detail page shows and what the sheet-level roll-up scores over. A sheet
    filed under `unfiled` still covers whatever its exercises cover.
    """
    competency_ids = list(
        db.execute(
            select(exercise_competency.c.competency_id)
            .join(Exercise, Exercise.id == exercise_competency.c.exercise_id)
            .join(SheetItem, SheetItem.exercise_id == Exercise.id)
            .where(SheetItem.sheet_id == sheet_id)
            .where(SheetItem.school_id == school_id)
            .distinct()
        ).scalars()
    )
    # `scalars()` cannot narrow the Optional away for mypy even though the
    # WHERE clause already has: the filter is SQL, the type is Python.
    chapter_ids: list[uuid.UUID] = list(
        db.execute(
            select(Exercise.chapter_id)
            .join(SheetItem, SheetItem.exercise_id == Exercise.id)
            .where(SheetItem.sheet_id == sheet_id)
            .where(SheetItem.school_id == school_id)
            # `Exercise.chapter_id` is itself an inference and is null on a
            # large minority of a real textbook. An untagged item contributes
            # no Theme rather than a guessed one.
            .where(Exercise.chapter_id.is_not(None))
            .distinct()
        )
        .scalars()
        .all()  # type: ignore[arg-type]  # NOT NULL is enforced by the WHERE above
    )
    return sorted(competency_ids, key=str), sorted(chapter_ids, key=str)


def set_sources(db: Session, sheet: Sheet, sources: list[Sheet]) -> None:
    """Record every sheet whose results justified this one, principal first.

    ``derived_from_id`` and ``sheet_source`` position 0 are the same fact
    reached two ways, so they are written together and asserted equal — a
    lineage where the feedback page names one sheet and the tree draws another
    is worse than no lineage at all (D70).
    """
    db.execute(sheet_source.delete().where(sheet_source.c.sheet_id == sheet.id))
    if not sources:
        sheet.derived_from_id = None
        return

    seen: list[Sheet] = []
    for candidate in sources:
        # A sheet cannot answer itself, and a repeat is a teacher clicking
        # twice, not a second piece of evidence.
        if candidate.id == sheet.id or any(candidate.id == s.id for s in seen):
            continue
        seen.append(candidate)

    sheet.derived_from_id = seen[0].id if seen else None
    if seen:
        db.execute(
            sheet_source.insert(),
            [
                {"sheet_id": sheet.id, "source_sheet_id": s.id, "position": position}
                for position, s in enumerate(seen)
            ],
        )
    db.flush()


def create_adaptive_sheet(
    db: Session, scope: Scope, teacher_id: uuid.UUID, payload: AdaptiveBatchRequest
) -> Sheet:
    """One sheet, N different printed pages — the F4 deliverable.

    The class-level item list is the union of every student's items so the
    corpus reference is complete; each instance's ``item_plan`` is that
    student's own ordered subset, which is what the renderer prints.
    """
    school_id = scope.school_id
    school_class = get_class(db, scope, payload.class_id)
    _require_subject(db, school_id, payload.subject_id)
    if not payload.plans:
        raise errors.unprocessable("an adaptive batch needs at least one student plan")

    students = {s.id: s for s in list_students(db, scope, school_class.id)}
    unknown = [str(p.student_id) for p in payload.plans if p.student_id not in students]
    if unknown:
        raise errors.not_found("student", ids=unknown)

    union: list[uuid.UUID] = []
    for plan in payload.plans:
        for proposal in [*plan.retrieved, *plan.generated]:
            if proposal.exercise.id not in union:
                union.append(proposal.exercise.id)
    exercises = _load_exercises(db, school_id, union)

    # The approval gate, at the first door rather than the last. The client
    # sends exercise ids, so "the UI would not offer an unapproved item" is not
    # a guarantee — it is a hope about one caller. Refusing here means the
    # teacher hears about it while they are still looking at the plan, not when
    # a render job fails half an hour later.
    try:
        ensure_printable(exercises.values())
    except UnapprovedExerciseError as exc:
        raise errors.unprocessable(
            "this batch contains AI-generated exercises that have not been approved",
            exercise_ids=[str(i) for i in exc.exercise_ids],
        ) from exc

    # The same door, for the notes. A feedback page is generated text handed to
    # a child; it gets the gate the generated exercises get.
    note_ids = [p.feedback_id for p in payload.plans if p.feedback_id is not None]
    notes = _load_notes(db, school_id, note_ids)
    missing_notes = [str(i) for i in note_ids if i not in notes]
    if missing_notes:
        raise errors.not_found("feedback", ids=missing_notes)
    try:
        ensure_notes_printable(notes.values())
    except UnapprovedFeedbackError as exc:
        raise errors.unprocessable(
            "this batch contains feedback notes that have not been approved",
            feedback_ids=[str(i) for i in exc.feedback_ids],
        ) from exc

    # `SheetTarget.GROUP` has sat in the enum since 0001 with nothing ever
    # assigning it. A batch built from more than one personalised group is
    # exactly what it was reserved for.
    grouped = (payload.group_count or 0) > 1

    # The sheet this batch answers, resolved through `get_sheet` so it carries
    # the school AND ownership check (D23) — `/adaptive/batch` performs none of
    # its own. Before this it was filtered on `school_id` alone for the chapter
    # lookup and not at all for `derived_from_id`, so a foreign id was stored
    # verbatim and `render.py` later printed that sheet's title onto a feedback
    # page. A 404 is the right answer to a sheet the caller cannot see.
    # Every sheet this batch answers, principal first. Each one goes through
    # `get_sheet`, so a source the caller cannot see is a 404 rather than an id
    # stored verbatim (D61).
    sources = [get_sheet(db, scope, sid) for sid in payload.resolved_source_ids()]
    parent = sources[0] if sources else None

    # A differentiated batch answers a common sheet, so it belongs to the same
    # Theme: the reprise on fractions is filed under fractions, next to the
    # sheet whose results justified it. Only when the batch answers nothing
    # does it fall back to `unfiled` — and never to a Theme inferred from the
    # generated items, which would scatter one teaching unit across the tree.
    parent_chapter_id = (
        parent.chapter_id
        if parent is not None and parent.subject_id == payload.subject_id
        else None
    )
    chapter = _resolve_chapter(db, school_id, payload.subject_id, parent_chapter_id)

    sheet = Sheet(
        id=uuid.uuid4(),
        school_id=school_id,
        class_id=school_class.id,
        subject_id=payload.subject_id,
        chapter_id=chapter.id,
        created_by_id=teacher_id,
        title=payload.title,
        target=SheetTarget.GROUP if grouped else SheetTarget.STUDENT,
        language=payload.language,
        intent="adaptive batch",
        layout_version=LAYOUT_VERSION,
        derived_from_id=parent.id if parent is not None else None,
    )
    db.add(sheet)
    db.flush()
    set_sources(db, sheet, sources)

    _replace_items(
        db,
        school_id,
        sheet,
        [SheetItemIn(exercise_id=eid, position=idx) for idx, eid in enumerate(union)],
    )

    plans: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for plan in payload.plans:
        plans[plan.student_id] = [
            {"exercise_id": str(p.exercise.id), "variant_id": None, "position": idx}
            for idx, p in enumerate([*plan.retrieved, *plan.generated])
        ]
    _bind_instances(
        db,
        school_id,
        sheet,
        [students[p.student_id] for p in payload.plans],
        plans,
        group_labels={
            p.student_id: p.group_label for p in payload.plans if p.group_label
        },
        feedback_ids={
            p.student_id: p.feedback_id for p in payload.plans if p.feedback_id is not None
        },
    )
    event_service.record(
        db,
        school_id=school_id,
        kind=EventKind.ADAPTIVE_EXPORTED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={
            "groups": payload.group_count or 1,
            "copies": len(payload.plans),
            "items": len(union),
            "feedback": len(note_ids),
        },
    )
    db.refresh(sheet)
    return sheet


def _load_notes(
    db: Session, school_id: uuid.UUID, note_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, MisconceptionNote]:
    """The notes this batch references, scoped to the school."""
    if not note_ids:
        return {}
    rows = db.scalars(
        select(MisconceptionNote).where(
            MisconceptionNote.school_id == school_id,
            MisconceptionNote.id.in_(list(note_ids)),
        )
    )
    return {row.id: row for row in rows}


@dataclass(frozen=True, slots=True)
class SheetPoints:
    """One copy's marks: what the student has, and what the copy was worth."""

    #: Points earned, floored at 0. None when nothing has been graded yet —
    #: which is not the same as zero, and a report that showed 0 for a pile
    #: nobody has scanned would be saying something false.
    earned: float | None
    #: The sum of what a correct answer earns over this copy's own items.
    possible: float


def _possible_by_student(sheet: Sheet, *, live: bool = False) -> dict[uuid.UUID, float]:
    """What each copy of this sheet was worth, from ITS OWN item plan.

    Factored out so a class-wide rollup reuses this instead of re-deriving what
    a differentiated copy was worth. A differentiated batch hands each student
    a different subset, so the sheet's class-wide item list is not what any one
    student held, and two places computing that separately would eventually
    disagree.

    **A confirmed copy answers with the total it was confirmed at** (B18). Until
    then this recomputed on every read, so editing the barème after a pile came
    back rewrote the denominator of every paper already handed out — 14/20
    became 14/25 on a sheet a parent may have signed. `SheetInstance.points_possible`
    is NULL until the copy is confirmed, so an unconfirmed one still tracks the
    barème as it stands, which is what the builder needs.

    ``live=True`` forces the computation, and has exactly one caller: the freeze
    itself, which needs today's arithmetic in order to store it.
    """
    items_by_exercise = {item.exercise_id: item for item in sheet.items}
    default_points = sheet.default_points_correct
    possible: dict[uuid.UUID, float] = {}
    for instance in sheet.instances:
        plan = instance.item_plan or [
            {"exercise_id": str(item.exercise_id)} for item in sheet.items
        ]
        total = 0.0
        for entry in plan:
            raw = entry.get("exercise_id")
            if raw is None:
                continue
            item = items_by_exercise.get(uuid.UUID(str(raw)))
            # `is not None` rather than `or`: a deliberate 0 is an item that
            # earns nothing, not an item with no override.
            if item is not None and item.points_correct is not None:
                total += item.points_correct
            else:
                total += default_points
        # The frozen total wins whenever there is one.
        frozen = None if live else instance.points_possible
        possible[instance.student_id] = total if frozen is None else frozen
    return possible


def _earned_by_sheet(
    db: Session, school_id: uuid.UUID, sheet_ids: Sequence[uuid.UUID]
) -> dict[tuple[uuid.UUID, uuid.UUID], float]:
    """``(person, sheet) -> earned``, floored at zero, in one query for N sheets.

    Keyed on the person since 0028, like every other read of ``Attempt``. The
    callers hold ``Student`` rows and translate — ``people_for_instances`` is
    the join.

    One query rather than one per sheet: a term's worth of sheets for a class is
    the normal case, and this is read on every dashboard load.
    """
    if not sheet_ids:
        return {}
    rows = db.execute(
        select(Attempt.person_id, Attempt.sheet_id, func.sum(Attempt.score))
        .where(Attempt.sheet_id.in_(list(sheet_ids)))
        .where(Attempt.school_id == school_id)
        .group_by(Attempt.person_id, Attempt.sheet_id)
    ).all()
    return {
        (person_id, sheet_id): max(0.0, float(total))
        for person_id, sheet_id, total in rows
        if total is not None
    }


def points_totals_for_sheet(
    db: Session, school_id: uuid.UUID, sheet: Sheet
) -> dict[uuid.UUID, SheetPoints]:
    """Each copy's total, keyed by student.

    Computed, never stored. ``Attempt.score`` is already the durable per-item
    record and is rewritten on every confirmation, so a SUM over it is exactly
    as fresh as the attempts themselves; a stored total would be one more place
    to disagree with them the first time a teacher corrects a single detection.

    The total floors at zero. Individual scores stay signed in the record, so a
    teacher can still see which answers cost points — only the sum is clamped,
    because a mark below zero says nothing a report can use.
    """
    earned = _earned_by_sheet(db, school_id, [sheet.id])
    # `_earned_by_sheet` is keyed by person (0028), `_possible_by_student` by
    # the copy that was printed. This is the join between them, and it is why
    # the response stays keyed by student: a sheet is one class in one year,
    # and that is what a `student` row is.
    person_of = people_for_students(
        db, school_id, [i.student_id for i in sheet.instances]
    )
    return {
        student_id: SheetPoints(
            earned=earned.get((person_of.get(student_id, student_id), sheet.id)),
            possible=possible,
        )
        for student_id, possible in _possible_by_student(sheet).items()
    }


@dataclass(frozen=True, slots=True)
class ClassSheetPoints:
    """One sheet, as the class did on it."""

    sheet_id: uuid.UUID
    sheet_title: str
    #: Mean of each graded copy's own ratio. None when nobody has been graded
    #: on it yet — which is not zero, and a report that showed 0% for a pile
    #: nobody has scanned would be saying something false.
    average_ratio: float | None
    per_student: dict[uuid.UUID, SheetPoints]


@dataclass(frozen=True, slots=True)
class ClassPointsReport:
    #: Totals ACROSS every sheet in scope, per student.
    students: dict[uuid.UUID, SheetPoints]
    sheets: list[ClassSheetPoints]


def class_points_totals(
    db: Session,
    scope: Scope,
    class_id: uuid.UUID,
    *,
    subject_id: uuid.UUID | None = None,
    chapter_id: uuid.UUID | None = None,
) -> ClassPointsReport:
    """Every sheet of a class, rolled up per student and per sheet.

    ``possible`` accumulates over every sheet whether or not it has been
    scanned: it is a fact about the paper the student was handed. ``earned``
    accumulates only where there is a grade, and stays ``None`` for a student
    with none — the same "absent is not zero" rule ``SheetPoints`` already
    states, one level up. A term where two of five sheets are marked must not
    read as though the other three were failed.
    """
    school_id = scope.school_id
    get_class(db, scope, class_id)
    sheets = list_sheets(
        db, scope, class_id=class_id, subject_id=subject_id, chapter_id=chapter_id
    )
    if not sheets:
        return ClassPointsReport(students={}, sheets=[])

    earned_by_sheet = _earned_by_sheet(db, school_id, [sheet.id for sheet in sheets])
    # Person-keyed evidence, student-keyed report — the same join
    # `points_totals_for_sheet` makes, over every sheet at once (0028).
    person_of = people_for_students(
        db, school_id, [i.student_id for sheet in sheets for i in sheet.instances]
    )
    earned_total: dict[uuid.UUID, float] = {}
    possible_total: dict[uuid.UUID, float] = {}
    graded_students: set[uuid.UUID] = set()
    per_sheet: list[ClassSheetPoints] = []

    for sheet in sheets:
        per_student: dict[uuid.UUID, SheetPoints] = {}
        ratios: list[float] = []
        for student_id, possible in _possible_by_student(sheet).items():
            earned = earned_by_sheet.get(
                (person_of.get(student_id, student_id), sheet.id)
            )
            per_student[student_id] = SheetPoints(earned=earned, possible=possible)
            possible_total[student_id] = possible_total.get(student_id, 0.0) + possible
            if earned is not None:
                earned_total[student_id] = earned_total.get(student_id, 0.0) + earned
                graded_students.add(student_id)
                if possible > 0:
                    ratios.append(earned / possible)
        per_sheet.append(
            ClassSheetPoints(
                sheet_id=sheet.id,
                sheet_title=sheet.title,
                average_ratio=(sum(ratios) / len(ratios)) if ratios else None,
                per_student=per_student,
            )
        )

    students = {
        student_id: SheetPoints(
            earned=earned_total.get(student_id) if student_id in graded_students else None,
            possible=possible,
        )
        for student_id, possible in possible_total.items()
    }
    return ClassPointsReport(students=students, sheets=per_sheet)
