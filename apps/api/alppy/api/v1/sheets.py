"""Sheet proposal, CRUD, rendering and preview.

``/sheets/propose`` is the one read path that can reach a model provider, so it
is rate limited per teacher. Rendering is a job: a headless-Chromium PDF pass
over 24 instances is not something a request should hold a connection open for.
Rendering and preview are limited too, on their own bucket — they cost the API
box rather than the provider bill, and a preview must never spend a teacher's
generation budget (D82).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from alppy.api import errors
from alppy.api.deps import (
    AiRateLimit,
    DbDep,
    RenderRateLimit,
    ScopeDep,
    StorageDep,
    TeacherDep,
    load_optional,
    start_job,
)
from alppy.core.config import get_settings
from alppy.models import Job
from alppy.models.enums import EventKind, EventSubject, JobKind, JobStatus, SheetKind
from alppy.schemas import (
    JobOut,
    SheetCreate,
    SheetDraftPreview,
    SheetMasteryOut,
    SheetOut,
    SheetProposeRequest,
    SheetProposeResponse,
    SheetStudentMastery,
    SheetUpdate,
)
from alppy.services import event_service, job_out, mastery_service, sheet_out
from alppy.services import sheet_service as svc
from alppy.services.class_service import get_class

router = APIRouter(tags=["sheets"])


@router.post(
    "/sheets/propose", response_model=SheetProposeResponse, dependencies=[AiRateLimit]
)
def propose(
    payload: SheetProposeRequest, teacher: TeacherDep, scope: ScopeDep, db: DbDep
) -> SheetProposeResponse:
    """Ranked exercises for a lesson, each with the provenance to audit it."""
    get_class(db, scope, payload.class_id)
    propose_exercises = load_optional(
        "alppy.services.retrieval", "propose_exercises", feature="exercise retrieval"
    )
    language = payload.language or str(teacher.locale) or get_settings().default_locale
    proposals = propose_exercises(
        db,
        school_id=scope.school_id,
        class_id=payload.class_id,
        subject_id=payload.subject_id,
        chapter_ids=list(payload.chapter_ids),
        intent=payload.intent,
        count=payload.count,
        language=language,
        difficulty=payload.difficulty,
    )
    return SheetProposeResponse(proposals=list(proposals), language=language)


@router.get("/sheets", response_model=list[SheetOut])
def list_sheets(
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
    class_id: Annotated[uuid.UUID | None, Query()] = None,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    school_year_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[SheetOut]:
    """The sheets this teacher may see.

    ``school_year_id`` narrows to one year's sheets, through the class each was
    printed for — a class code is reused every August (audit 02, C3).
    """
    return [
        sheet_out(s, storage=storage, points=svc.points_totals_for_sheet(db, scope.school_id, s))
        for s in svc.list_sheets(
            db,
            scope,
            class_id=class_id,
            subject_id=subject_id,
            school_year_id=school_year_id,
        )
    ]


@router.post("/sheets", response_model=SheetOut, status_code=status.HTTP_201_CREATED)
def create_sheet(
    payload: SheetCreate,
    teacher: TeacherDep,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> SheetOut:
    sheet = svc.create_sheet(db, scope, teacher.id, payload)
    db.commit()
    db.refresh(sheet)
    return sheet_out(
        sheet, storage=storage, points=svc.points_totals_for_sheet(db, scope.school_id, sheet)
    )


@router.get("/sheets/{sheet_id}", response_model=SheetOut)
def get_sheet(
    sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep, storage: StorageDep
) -> SheetOut:
    sheet = svc.get_sheet(db, scope, sheet_id)
    return sheet_out(
        sheet, storage=storage, points=svc.points_totals_for_sheet(db, scope.school_id, sheet)
    )


@router.patch("/sheets/{sheet_id}", response_model=SheetOut)
def update_sheet(
    sheet_id: uuid.UUID,
    payload: SheetUpdate,
    scope: ScopeDep,
    db: DbDep,
    storage: StorageDep,
) -> SheetOut:
    sheet = svc.update_sheet(db, scope, sheet_id, payload)
    db.commit()
    db.refresh(sheet)
    return sheet_out(
        sheet, storage=storage, points=svc.points_totals_for_sheet(db, scope.school_id, sheet)
    )


@router.post(
    "/sheets/{sheet_id}/render",
    response_model=JobOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[RenderRateLimit],
)
def render_sheet(sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep) -> JobOut:
    """Queue the blank sheet and the answer key. Returns the job to poll."""
    sheet = svc.get_sheet(db, scope, sheet_id)
    if not sheet.items:
        raise errors.unprocessable("a sheet with no items cannot be rendered")
    load_optional("alppy.sheets.render", "render_sheet_pdfs", feature="PDF rendering")

    # Lay the sheet out before queueing it. Pagination is pure and fast, and it
    # is where "this statement cannot fit on a page" is discovered — the teacher
    # should be told that now, not by a job that fails two seconds later.
    _assert_printable(db, sheet)

    job = Job(
        id=uuid.uuid4(),
        school_id=scope.school_id,
        kind=JobKind.RENDER_SHEET,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="queued for rendering",
        payload={"sheet_id": str(sheet.id)},
    )
    event_service.record(
        db,
        school_id=scope.school_id,
        kind=EventKind.SHEET_RENDERED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=scope.teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={"items": len(sheet.items), "copies": len(sheet.instances)},
    )
    db.add(job)
    db.commit()
    start_job(db, job)
    db.refresh(job)
    return job_out(job)


def _not_renderable(exc: Exception, render_error: Any) -> errors.ApiError:
    """A sheet the renderer will not lay out, as one code the client can localise.

    ``message`` is passed through only for ``SheetRenderError`` — our own type,
    whose text is authored for a reader. Everything else caught here is a bare
    ``ValueError``, which can just as easily have come from a library several
    frames down as from us, and its text is not something to put in front of a
    teacher. The frontend renders `errors.code.sheet_not_renderable` either way;
    ``message`` is for the log.
    """
    authored = isinstance(exc, render_error)
    return errors.unprocessable(
        str(exc) if authored else "this sheet cannot be laid out",
        code="sheet_not_renderable",
    )


def _assert_printable(db: DbDep, sheet: Any) -> None:
    """422 if this sheet cannot be laid out, with the reason."""
    build_sheet_data = load_optional(
        "alppy.sheets.render", "build_sheet_data", feature="PDF rendering"
    )
    physical_pages = load_optional(
        "alppy.sheets.html", "physical_pages", feature="PDF rendering"
    )
    render_error = load_optional(
        "alppy.sheets.render", "SheetRenderError", feature="PDF rendering"
    )
    try:
        physical_pages(build_sheet_data(db, sheet))
    except (render_error, ValueError) as exc:
        raise _not_renderable(exc, render_error) from exc


@router.post("/sheets/preview", response_class=Response, dependencies=[RenderRateLimit])
def preview_draft(
    payload: SheetDraftPreview, scope: ScopeDep, db: DbDep
) -> Response:
    """Render a sheet that has not been saved yet.

    The builder shows this while the teacher is still ticking and reordering,
    which is the only moment the information is worth anything: it is where a
    sixth exercise turning into a second sheet of paper, or a statement too tall
    for any page, becomes visible *before* 72 pages come off the photocopier.

    Nothing is written. That is the point — the alternative was to POST a real
    draft `Sheet` and PATCH it on every edit, which rewrites one `SheetInstance`
    per student per keystroke and abandons a junk row whenever the teacher
    changes their mind.

    Same `SheetData`, same templates, same `physical_pages` as the saved
    preview and the PDF, so it cannot drift from the paper.
    """
    get_class(db, scope, payload.class_id)
    build_draft = load_optional(
        "alppy.sheets.render", "build_draft_sheet_data", feature="sheet preview"
    )
    render_html = load_optional(
        "alppy.sheets.html", "render_sheet_html", feature="sheet preview"
    )
    render_error = load_optional(
        "alppy.sheets.render", "SheetRenderError", feature="sheet preview"
    )
    try:
        data = build_draft(
            db,
            school_id=scope.school_id,
            class_id=payload.class_id,
            subject_id=payload.subject_id,
            title=payload.title,
            language=str(payload.language),
            items=payload.items,
            # The draft has no Sheet row to read a default off, so it rides in
            # with the payload — otherwise the preview prints "(1 pt)" beside
            # every statement while the saved sheet grades on something else.
            default_points_correct=payload.default_points_correct,
        )
        html: str = render_html(data, kind=SheetKind.BLANK)
    except (render_error, ValueError) as exc:
        # "no students", "this statement is taller than a page": the teacher
        # needs to know now rather than from a failed render job two minutes
        # later. They read the localised sentence for `sheet_not_renderable`;
        # the specific prose stays in `message`, for the log and the developer.
        raise _not_renderable(exc, render_error) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get(
    "/sheets/{sheet_id}/preview", response_class=Response, dependencies=[RenderRateLimit]
)
def preview_sheet(
    sheet_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    kind: SheetKind = SheetKind.BLANK,
) -> Response:
    """The same markup the PDF renderer prints, served as HTML.

    Literally the same: the renderer takes a ``SheetData`` assembled from the
    rows, so the preview cannot drift from the paper. It used to be called as
    ``render_sheet_html(db, sheet_id=...)``, a signature that does not exist,
    and answered 500 on every request.
    """
    sheet = svc.get_sheet(db, scope, sheet_id)
    build_sheet_data = load_optional(
        "alppy.sheets.render", "build_sheet_data", feature="sheet preview"
    )
    render_html = load_optional(
        "alppy.sheets.html", "render_sheet_html", feature="sheet preview"
    )
    render_error = load_optional(
        "alppy.sheets.render", "SheetRenderError", feature="sheet preview"
    )
    try:
        data = build_sheet_data(db, sheet)
        html: str = render_html(data, kind=kind)
    except (render_error, ValueError) as exc:
        # "no students", "no items", a malformed UID: the sheet cannot be shown,
        # and that is a refusal rather than a 500.
        raise _not_renderable(exc, render_error) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.post("/sheets/{sheet_id}/printed", response_model=SheetOut)
def mark_printed(
    sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep, storage: StorageDep
) -> SheetOut:
    """Record that this sheet went to the photocopier.

    The one lifecycle moment nothing in the schema could observe. `rendered_at`
    is when the PDF was built, which is not the same thing and is often days
    earlier — a teacher renders on Sunday and prints on Tuesday morning. The
    client calls this when the download is actually taken, so the agenda can
    answer "when did 7B actually sit this".
    """
    sheet = svc.get_sheet(db, scope, sheet_id)
    event_service.record(
        db,
        school_id=scope.school_id,
        kind=EventKind.SHEET_PRINTED,
        subject_type=EventSubject.SHEET,
        subject_id=sheet.id,
        summary=sheet.title,
        actor_id=scope.teacher_id,
        class_id=sheet.class_id,
        subject_area_id=sheet.subject_id,
        detail={"copies": len(sheet.instances)},
    )
    db.commit()
    db.refresh(sheet)
    return sheet_out(
        sheet, storage=storage, points=svc.points_totals_for_sheet(db, scope.school_id, sheet)
    )


@router.get("/sheets/{sheet_id}/mastery", response_model=SheetMasteryOut)
def sheet_mastery(
    sheet_id: uuid.UUID,
    scope: ScopeDep,
    db: DbDep,
    as_of: Annotated[datetime | None, Query()] = None,
) -> SheetMasteryOut:
    """How the class did on one sheet, in the product's five bands.

    The altitude the model was missing. `MasterySnapshot` answers "how is this
    child doing on X" and the tree answers it for a Theme; nothing answered
    "how did they do on *this sheet*" without leaving the product's vocabulary
    for a percentage.

    Computed from attempts, not read from a snapshot, for the same reason the
    matrix is: the score decays, so a sheet opened on Friday must not show
    Monday's numbers.

    Works unchanged on an adaptive batch — `Sheet.target` does not enter the
    arithmetic — which is what makes "adaptive sheet mastery" the same
    function rather than a second one that could drift from it.
    """
    sheet = svc.get_sheet(db, scope, sheet_id)
    competency_ids, _chapter_ids = svc.sheet_coverage(db, scope.school_id, sheet.id)
    # A sheet instance is one year's paper, so it carries a `student_id`; the
    # mastery behind it is the person's. The map back out keeps the response
    # keyed the way the web client addresses a pupil (0028).
    people = svc.people_for_instances(db, scope.school_id, sheet.instances)
    person_ids = list(people.values())
    by_person = mastery_service.sheet_mastery(
        db, scope.school_id, sheet.id, person_ids, competency_ids, now=as_of
    )

    return SheetMasteryOut(
        sheet_id=sheet.id,
        competency_ids=competency_ids,
        students=[
            SheetStudentMastery(student_id=sid, mastery=by_person[pid])
            for sid, pid in people.items()
            if pid in by_person
        ],
        overall=mastery_service.sheet_mastery_overall(
            db, scope.school_id, sheet.id, person_ids, competency_ids, now=as_of
        ),
        # What the answer is AS OF, which is what a reader has to know to
        # interpret a band that decays. Not "when this request ran".
        computed_at=as_of or datetime.now(UTC),
    )
