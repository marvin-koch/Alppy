"""Sheet proposal, CRUD, rendering and preview.

``/sheets/propose`` is the one read path that can reach a model provider, so it
is rate limited per teacher. Rendering is a job: a headless-Chromium PDF pass
over 24 instances is not something a request should hold a connection open for.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response, status

from alppy.api import errors
from alppy.api.deps import (
    AiRateLimit,
    DbDep,
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
    SheetOut,
    SheetProposeRequest,
    SheetProposeResponse,
    SheetUpdate,
)
from alppy.services import event_service, job_out, sheet_out
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
) -> list[SheetOut]:
    return [
        sheet_out(s, storage=storage)
        for s in svc.list_sheets(db, scope, class_id=class_id)
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
    return sheet_out(sheet, storage=storage)


@router.get("/sheets/{sheet_id}", response_model=SheetOut)
def get_sheet(
    sheet_id: uuid.UUID, scope: ScopeDep, db: DbDep, storage: StorageDep
) -> SheetOut:
    return sheet_out(svc.get_sheet(db, scope, sheet_id), storage=storage)


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
    return sheet_out(sheet, storage=storage)


@router.post(
    "/sheets/{sheet_id}/render", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED
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
        raise errors.unprocessable(str(exc)) from exc


@router.post("/sheets/preview", response_class=Response)
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
        )
        html: str = render_html(data, kind=SheetKind.BLANK)
    except (render_error, ValueError) as exc:
        # "no students", "this statement is taller than a page": the teacher
        # needs to read which, and needs to read it now rather than from a
        # failed render job two minutes later.
        raise errors.unprocessable(str(exc)) from exc
    return Response(content=html, media_type="text/html; charset=utf-8")


@router.get("/sheets/{sheet_id}/preview", response_class=Response)
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
        # "no students", "no items", a malformed UID: the sheet cannot be shown
        # and the teacher needs to know which, not a 500.
        raise errors.unprocessable(str(exc)) from exc
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
    return sheet_out(sheet, storage=storage)
