"""Adaptive, per-student sheets — the focal deliverable (F4).

Both planning endpoints can reach a model provider, so both are rate limited.
The planning itself lives in ``alppy.services.adaptive_service``; this module
owns the tenancy check, the limit, and turning an approved plan into printable
instances.

The approval endpoints (`/adaptive/approve`, `/adaptive/discard`) reach the gate
in ``alppy.services.approval`` directly rather than through ``load_optional``.
The gate is never optional: a deployment without the adaptive planner still must
not be able to print an unapproved item, and an approval route that 503s would
leave a teacher with items they cannot clear.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from sqlalchemy import select

from alppy.api import errors
from alppy.api.deps import (
    AiBudget,
    AiRateLimit,
    DbDep,
    IdempotencyKeyDep,
    RenderRateLimit,
    ScopeDep,
    StorageDep,
    TeacherDep,
    load_optional,
    start_job,
)
from alppy.core.config import get_settings
from alppy.models import AdaptiveProposal, Job, MisconceptionNote, Student
from alppy.models.enums import EventKind, EventSubject, JobKind, JobStatus
from alppy.schemas import (
    AdaptiveApproveRequest,
    AdaptiveApproveResponse,
    AdaptiveBatchRequest,
    AdaptiveDiscardRequest,
    AdaptiveDiscardResponse,
    AdaptiveProposeRequest,
    AdaptiveProposeResponse,
    AdaptiveRegenerateRequest,
    AdaptiveRegenerateResponse,
    FeedbackApproveRequest,
    FeedbackApproveResponse,
    FeedbackDiscardRequest,
    FeedbackDiscardResponse,
    FeedbackGenerateRequest,
    JobOut,
    MisconceptionNoteOut,
    SheetOut,
)
from alppy.services import event_service, idempotency, job_out, sheet_out
from alppy.services import sheet_service as sheet_svc
from alppy.services.approval import (
    approve_exercises,
    approve_feedback,
    discard_exercises,
    discard_feedback,
)
from alppy.services.class_service import get_class, list_students

router = APIRouter(tags=["adaptive"])


@router.post(
    "/adaptive/propose",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AiRateLimit, AiBudget],
)
def propose(
    payload: AdaptiveProposeRequest, teacher: TeacherDep, scope: ScopeDep, db: DbDep
) -> JobOut:
    """Queue the targeting, retrieval and generation for a class.

    A job rather than a synchronous response because it makes model calls, and
    CLAUDE.md is explicit that nothing blocks a request handler on one. Batching
    took a class of twenty-four from twenty-four calls to three, which made the
    old shape survivable rather than correct.

    The rate limit stays on this handler even though it now only enqueues: it is
    the only door in front of the worker's fan-out, and without it a teacher can
    queue twenty proposals a minute. The in-flight check below is the other half
    — a double-click used to cost one token and now costs a second Job and a
    second set of unapproved Exercise rows.

    Poll ``GET /jobs/{id}``; read the result from
    ``GET /adaptive/proposal/{job_id}`` once it succeeds.
    """
    school_class = get_class(db, scope, payload.class_id)
    student_ids = list(payload.student_ids)
    if student_ids:
        known = {s.id for s in list_students(db, scope, school_class.id)}
        unknown = [str(i) for i in student_ids if i not in known]
        if unknown:
            raise errors.not_found("student", ids=unknown)
    else:
        student_ids = [s.id for s in list_students(db, scope, school_class.id)]
    if not student_ids:
        raise errors.unprocessable("this class has no students yet")

    # Fail here rather than in the worker: a class with no adaptive module
    # installed should say so at the moment the teacher asks.
    load_optional(
        "alppy.services.adaptive_service", "propose_adaptive", feature="adaptive planning"
    )

    running = db.scalars(
        select(Job).where(
            Job.school_id == scope.school_id,
            Job.kind == JobKind.PROPOSE_ADAPTIVE,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            Job.class_id == school_class.id,
            Job.subject_id == payload.subject_id,
            Job.created_by_id == scope.teacher_id,
        )
    ).first()
    if running is not None:
        # Not an error. The second click wanted the thing the first one is
        # already doing, and starting a second run would write a second set of
        # unapproved exercises for the same class.
        #
        # Keyed on the teacher as well as the class and the branch, because the
        # payload below carries `items_per_student`, `group`, `n_groups`,
        # `source_sheet_id` and `language`. Matching on the school alone handed
        # a co-teacher the job their colleague had started, built to their
        # colleague's parameters — they asked for eight items in three groups
        # and silently got five ungrouped (audit 02, C1).
        return job_out(running)

    job = Job(
        id=uuid.uuid4(),
        school_id=scope.school_id,
        kind=JobKind.PROPOSE_ADAPTIVE,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for adaptive planning",
        class_id=school_class.id,
        subject_id=payload.subject_id,
        created_by_id=scope.teacher_id,
        payload={
            "class_id": str(payload.class_id),
            "subject_id": str(payload.subject_id),
            "student_ids": [str(i) for i in student_ids],
            "items_per_student": payload.items_per_student,
            "allow_generation": payload.allow_generation,
            # An explicit teacher override, normally absent. The sheet's language
            # follows the source material; the locale is only the last resort for
            # a subject with nothing indexed yet.
            "language": payload.language,
            "fallback_language": str(teacher.locale) or get_settings().default_locale,
            "group": payload.group,
            "n_groups": payload.n_groups,
            "source_sheet_id": (
                str(payload.source_sheet_id) if payload.source_sheet_id else None
            ),
            "llm_grouping": payload.llm_grouping,
        },
    )
    db.add(job)
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)


@router.get("/adaptive/proposal/{job_id}", response_model=AdaptiveProposeResponse)
def read_proposal(
    job_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> AdaptiveProposeResponse:
    """The proposal a finished job built.

    Its own endpoint rather than a field on ``JobOut``: the screen polls the job
    every 900 ms while it runs, and a class of twenty-four with eight items each
    is close to a megabyte of statements and provenance. A status row has to stay
    cheap to ask about.
    """
    job = db.get(Job, job_id)
    if job is None or job.school_id != scope.school_id:
        raise errors.not_found("job", ids=[str(job_id)])
    # Tenancy is not the boundary here: a proposal names which children are
    # behind, on what, and what each of them should do next. Gate on the class
    # the job was queued for, through the same call `propose` makes — a
    # colleague's proposal reads as missing, never as forbidden (audit 02, C1).
    if job.class_id is None:
        raise errors.not_found("proposal", ids=[str(job_id)])
    get_class(db, scope, job.class_id)

    row = db.scalars(
        select(AdaptiveProposal).where(
            AdaptiveProposal.school_id == scope.school_id,
            AdaptiveProposal.job_id == job_id,
        )
    ).first()
    if row is None:
        raise errors.not_found("proposal", ids=[str(job_id)])

    response = AdaptiveProposeResponse.model_validate(row.payload)

    # Attach whatever feedback exists for these students on the common sheet, so
    # the review screen shows the notes beside the plans they explain. Read here
    # rather than baked into the stored proposal: the teacher can write and
    # approve notes after the plan was built, and a frozen copy would go stale.
    source_sheet_id = (job.payload or {}).get("source_sheet_id")
    if source_sheet_id:
        from alppy.services.feedback_service import latest_for_people
        from alppy.services.sheet_service import people_for_students

        # A plan addresses a pupil in one year, so it carries a `student_id`; a
        # note explains a misconception, which is a fact about the person
        # (0028). One join, here, rather than two ids on the plan.
        person_of = people_for_students(
            db, scope.school_id, [p.student_id for p in response.plans]
        )
        notes = latest_for_people(
            db,
            school_id=scope.school_id,
            person_ids=list(person_of.values()),
            source_sheet_id=uuid.UUID(str(source_sheet_id)),
        )
        for plan in response.plans:
            person_id = person_of.get(plan.student_id)
            note = notes.get(person_id) if person_id is not None else None
            if note is not None:
                plan.feedback_id = note.id
    return response


@router.post("/adaptive/approve", response_model=AdaptiveApproveResponse)
def approve(
    payload: AdaptiveApproveRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveApproveResponse:
    """Approve generated exercises for printing.

    Returns the ids actually stamped, which is not necessarily the ids asked
    for: anything that is not an AI-generated exercise in this school is left
    alone. The client compares the two and can say so rather than assuming.
    """
    approved = approve_exercises(
        db, school_id=scope.school_id, exercise_ids=payload.exercise_ids
    )
    for exercise_id in approved:
        # One event per exercise rather than one per click: approval is a fact
        # about an item, and a batch of eleven approved at once is eleven items
        # that became printable (audit 03, B21). The flat staffroom means anyone
        # could have done this, which is exactly why it needs an author.
        event_service.record(
            db,
            school_id=scope.school_id,
            kind=EventKind.EXERCISE_APPROVED,
            subject_type=EventSubject.EXERCISE,
            subject_id=exercise_id,
            actor_id=scope.teacher_id,
        )
    db.commit()
    return AdaptiveApproveResponse(approved=len(approved), exercise_ids=approved)


@router.post("/adaptive/discard", response_model=AdaptiveDiscardResponse)
def discard(
    payload: AdaptiveDiscardRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveDiscardResponse:
    """Throw generated exercises away. They are never proposed or printed again."""
    discarded = discard_exercises(
        db, school_id=scope.school_id, exercise_ids=payload.exercise_ids
    )
    db.commit()
    return AdaptiveDiscardResponse(discarded=len(discarded), exercise_ids=discarded)


@router.post(
    "/adaptive/regenerate",
    response_model=AdaptiveRegenerateResponse,
    dependencies=[AiRateLimit, AiBudget],
)
def regenerate(
    payload: AdaptiveRegenerateRequest, scope: ScopeDep, db: DbDep
) -> AdaptiveRegenerateResponse:
    """Replace one generated item with a fresh one aimed at the same gap.

    Replaces, never appends: the old item is discarded in the same transaction,
    so the sheet keeps its length and the rejected version cannot come back.
    """
    regenerate_exercise = load_optional(
        "alppy.services.adaptive_service", "regenerate_exercise", feature="adaptive planning"
    )
    generation_error = load_optional(
        "alppy.services.adaptive_service", "AdaptiveGenerationError", feature="adaptive planning"
    )
    try:
        proposal = regenerate_exercise(db, school_id=scope.school_id, exercise_id=payload.exercise_id)
    except generation_error as exc:
        raise errors.unprocessable(f"could not regenerate this exercise: {exc}") from exc
    return AdaptiveRegenerateResponse(
        replaced_exercise_id=payload.exercise_id, proposal=proposal
    )


@router.post(
    "/adaptive/batch",
    response_model=SheetOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[AiRateLimit, AiBudget],
)
def create_batch(
    payload: AdaptiveBatchRequest,
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
    idem: IdempotencyKeyDep = None,
) -> SheetOut:
    """Turn approved plans into one sheet with a different page per student.

    Creating the sheet is not rendering it: the caller follows this with
    ``POST /adaptive/batch/{id}/render``, which returns the job to poll. Two
    calls because binding 28 students to their item lists is fast and
    synchronous, while driving a headless browser over 170 pages is not.

    Honours ``Idempotency-Key`` (audit 03, B17): a retry used to build a second
    sheet binding the same pupils to the same plans, so the teacher printed one
    of the two and the other sat in the list looking identical.
    """

    def _work() -> SheetOut:
        sheet = sheet_svc.create_adaptive_sheet(db, scope, teacher.id, payload)
        db.commit()
        db.refresh(sheet)
        return sheet_out(sheet, storage=storage)

    return idempotency.run(
        db,
        school_id=scope.school_id,
        endpoint="adaptive.batch",
        key=idem,
        model=SheetOut,
        work=_work,
    )


@router.post(
    "/adaptive/batch/{sheet_id}/render",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[RenderRateLimit],
)
def render_batch(
    sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep, idem: IdempotencyKeyDep = None
) -> JobOut:
    """Queue the single PDF that holds every student's page, in order."""
    return idempotency.run(
        db,
        school_id=scope.school_id,
        endpoint="adaptive.batch.render",
        key=idem,
        model=JobOut,
        work=lambda: _render_batch(sheet_id, scope, db),
    )


def _render_batch(sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> JobOut:
    sheet = sheet_svc.get_sheet(db, scope, sheet_id)
    if not sheet.instances:
        raise errors.unprocessable("this batch has no student instances to print")
    load_optional("alppy.sheets.render", "render_adaptive_batch", feature="PDF rendering")

    job = Job(
        id=uuid.uuid4(),
        school_id=scope.school_id,
        kind=JobKind.GENERATE_ADAPTIVE,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for batch rendering",
        payload={"sheet_id": str(sheet.id)},
    )
    db.add(job)
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)


# --------------------------------------------------------------------------
# Per-student feedback
# --------------------------------------------------------------------------
@router.post(
    "/adaptive/feedback/generate",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[AiRateLimit, AiBudget],
)
def generate_feedback(
    payload: FeedbackGenerateRequest, teacher: TeacherDep, scope: ScopeDep, db: DbDep
) -> JobOut:
    """Queue one misconception note per student, read off a corrected sheet.

    Queued rather than synchronous because it is one model call per student:
    a class of twenty inside a request handler is a timeout with a half-written
    batch behind it (CLAUDE.md — nothing blocks a request handler on a model
    call).

    Rate-limited and guarded for exactly the reasons ``propose`` is, and it had
    neither (audit 03, B13). It is one model call **per student**, so a class of
    twenty-four is twenty-four calls behind a single unthrottled POST — the
    largest fan-out any endpoint in the product puts in front of the worker, and
    the only model-reaching route that was missing the limiter every one of its
    neighbours carries.
    """
    school_class = get_class(db, scope, payload.class_id)
    source = sheet_svc.get_sheet(db, scope, payload.source_sheet_id)
    if not list_students(db, scope, school_class.id):
        raise errors.unprocessable("this class has no students yet")
    load_optional(
        "alppy.services.feedback_service", "generate_for_sheet", feature="feedback generation"
    )

    running = db.scalars(
        select(Job).where(
            Job.school_id == scope.school_id,
            Job.kind == JobKind.GENERATE_FEEDBACK,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            Job.class_id == school_class.id,
            Job.created_by_id == scope.teacher_id,
        )
    ).first()
    # Keyed on `(class, source sheet, teacher)`. The source sheet is what makes
    # two runs genuinely different work — notes are written from one corrected
    # pile — and the teacher is on the key for the same reason it is on
    # `propose`: the payload carries a language, and handing a colleague the job
    # someone else started writes their notes in someone else's chosen language
    # (audit 02, C1).
    if running is not None and (running.payload or {}).get("source_sheet_id") == str(source.id):
        return job_out(running)

    job = Job(
        id=uuid.uuid4(),
        school_id=scope.school_id,
        kind=JobKind.GENERATE_FEEDBACK,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for feedback",
        # The same three columns `propose` fills (0029). They are what the
        # in-flight guard above reads: left NULL, the guard matches nothing and
        # is decoration.
        class_id=school_class.id,
        subject_id=payload.subject_id,
        created_by_id=scope.teacher_id,
        payload={
            "class_id": str(school_class.id),
            "subject_id": str(payload.subject_id),
            "source_sheet_id": str(source.id),
            "language": str(payload.language) if payload.language else source.language,
        },
    )
    db.add(job)
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)


@router.get("/adaptive/feedback", response_model=list[MisconceptionNoteOut])
def list_feedback(
    source_sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep
) -> list[MisconceptionNoteOut]:
    """Every live note written from one common sheet, newest per student."""
    from sqlalchemy import select

    # REPORT: listing notes already written from this sheet. Generating a
    # new one (`generate_feedback`) bills a model call and stays a gate.
    sheet_svc.get_sheet_for_read(db, scope, source_sheet_id)  # tenancy check
    rows = list(
        db.scalars(
            select(MisconceptionNote)
            .where(
                MisconceptionNote.school_id == scope.school_id,
                MisconceptionNote.based_on_sheet_id == source_sheet_id,
                MisconceptionNote.discarded_at.is_(None),
            )
            .order_by(MisconceptionNote.created_at.desc())
        )
    )
    # `school_id` is redundant here — every id came from a note already filtered
    # on it — and it is written anyway. A scoped query that leans on the query
    # above it is correct until someone widens that one. The lookup is by
    # primary key either way; the extra predicate is a comparison on rows
    # already fetched.
    #
    # This used to claim to be the only such site in the codebase. It was not:
    # `timeline._titles` had five lookups selecting by primary key alone and the
    # class-code lookup beside it a sixth, all of them inferring the tenant from
    # the query above rather than saying it (audit 03, B20). They say it now, so
    # the claim is retired rather than corrected — a comment that counts sites
    # is a comment that goes stale.
    #
    # Keyed on the person since 0028, and resolved back to a student to answer
    # with the uid the paper carries. A note may outlive the year it was
    # written in; the uid it is shown beside must be the uid of the year it
    # describes, which is why this looks the student up by person AND by the
    # sheet's own year rather than taking whichever row comes first.
    students = list(
        db.scalars(
            select(Student).where(
                Student.school_id == scope.school_id,
                Student.person_id.in_([r.person_id for r in rows] or [uuid.uuid4()]),
            )
        )
    )
    by_person = {s.person_id: s for s in students}
    seen: set[uuid.UUID] = set()
    out: list[MisconceptionNoteOut] = []
    for row in rows:
        if row.person_id in seen:
            continue
        seen.add(row.person_id)
        student = by_person.get(row.person_id)
        # A note this school owns whose person it cannot resolve is not dropped
        # — it is shown with a blank uid, exactly as before 0028. That row only
        # exists through a cross-school mistake, and hiding it would leave the
        # teacher unable to see the thing that needs fixing. The id echoed back
        # is the one the note points at, which is what this field has always
        # carried.
        out.append(
            MisconceptionNoteOut(
                id=row.id,
                student_id=student.id if student is not None else row.person_id,
                student_uid=student.uid if student is not None else "",
                subject_id=row.subject_id,
                based_on_sheet_id=row.based_on_sheet_id,
                language=row.language,
                notes=list(row.notes or []),
                competency_ids=[c.id for c in row.competencies],
                approved_at=row.approved_at,
                created_at=row.created_at,
            )
        )
    out.sort(key=lambda n: n.student_uid)
    return out


@router.post("/adaptive/feedback/approve", response_model=FeedbackApproveResponse)
def approve_notes(
    payload: FeedbackApproveRequest, scope: ScopeDep, db: DbDep
) -> FeedbackApproveResponse:
    """The only way a generated note becomes printable."""
    ids = approve_feedback(db, school_id=scope.school_id, feedback_ids=payload.feedback_ids)
    if ids:
        # Anchored to the common sheet the notes were read from: that is the
        # thing in the agenda a teacher would click to see what this was about.
        note = db.get(MisconceptionNote, ids[0])
        source = (
            sheet_svc.get_sheet(db, scope, note.based_on_sheet_id)
            if note is not None and note.based_on_sheet_id is not None
            else None
        )
        if source is not None:
            event_service.record(
                db,
                school_id=scope.school_id,
                kind=EventKind.FEEDBACK_APPROVED,
                subject_type=EventSubject.SHEET,
                subject_id=source.id,
                summary=source.title,
                actor_id=scope.teacher_id,
                class_id=source.class_id,
                subject_area_id=source.subject_id,
                detail={"notes": len(ids)},
            )
    db.commit()
    return FeedbackApproveResponse(approved=len(ids), feedback_ids=ids)


@router.post("/adaptive/feedback/discard", response_model=FeedbackDiscardResponse)
def discard_notes(
    payload: FeedbackDiscardRequest, scope: ScopeDep, db: DbDep
) -> FeedbackDiscardResponse:
    ids = discard_feedback(db, school_id=scope.school_id, feedback_ids=payload.feedback_ids)
    db.commit()
    return FeedbackDiscardResponse(discarded=len(ids), feedback_ids=ids)
