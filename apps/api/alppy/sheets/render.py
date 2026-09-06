"""Server-side PDF rendering — headless Chromium over the print markup.

There is one renderer for the browser preview and the PDF, and it is
``alppy.sheets.html``. This module only drives a browser over that HTML and puts
the bytes somewhere. Everything interesting — pagination, geometry, the UID grid,
the answer key — happens before Chromium is involved and is testable without it.

**Deterministic** means: the same sheet renders the same document every time. No
clock reaches the markup (dates arrive as an explicit label), copies are ordered
by UID rather than by database order, and page numbers are derived, not
accumulated. The PDF *bytes* still differ between runs — Chromium stamps a
creation date into the file metadata — so determinism is asserted against the
HTML, which is where all the decisions live.

If Chromium is missing, ``BrowserUnavailableError`` is raised with the command
that installs it. It is a distinct, catchable type precisely so a caller can tell
"the browser is not installed" apart from "this sheet cannot be rendered".
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from alppy.core.logging import get_logger
from alppy.models.enums import ExerciseOrigin, ExerciseType, SheetKind
from alppy.sheets import layout as L
from alppy.sheets.html import Copy, SheetData, physical_pages, render_sheet_html
from alppy.sheets.pagination import Item

log = get_logger(__name__)

RENDER_DIR_ENV: Final = "ALPPY_RENDER_DIR"
DEFAULT_RENDER_DIR: Final = "var/renders"
PDF_CONTENT_TYPE: Final = "application/pdf"

INSTALL_HINT: Final = (
    "pip install playwright && playwright install chromium"
)


class SheetRenderError(RuntimeError):
    """The sheet itself cannot be rendered — no students, no items, bad UID."""


class BrowserUnavailableError(RuntimeError):
    """Headless Chromium is not installed or refused to start.

    Separate from ``SheetRenderError`` on purpose: this one is an environment
    problem a deploy can fix, not a data problem."""


# --------------------------------------------------------------------------
# 1 · HTML -> PDF
# --------------------------------------------------------------------------
def html_to_pdf(html: str, *, timeout_ms: int = 60_000) -> bytes:
    """Render one standalone HTML document to an A4 PDF.

    ``print_background=False`` is the browser's own default for printing, and we
    keep it: every mark the scan pipeline depends on — the four fiducials, the
    set cells of the UID grid, a filled bubble on the answer key — is drawn with
    a *border*, never a background, so it survives a teacher printing from their
    own browser with backgrounds off. Rendering with backgrounds on would hide
    that mistake until the first scan came back unreadable.

    The margins are passed explicitly with the same value as the ``@page`` rule
    in print.css (``layout.MARGIN_MM``) because Chromium's own default margin is
    0.4 in; a silent 10 mm would shift every fiducial and every bubble.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise BrowserUnavailableError(
            f"playwright is not installed: {exc}. Install with: {INSTALL_HINT}"
        ) from exc

    margin = f"{L.MARGIN_MM:g}mm"
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception as exc:  # pragma: no cover - depends on the environment
                raise BrowserUnavailableError(
                    f"could not start headless Chromium: {exc}. Install with: {INSTALL_HINT}"
                ) from exc
            try:
                page = browser.new_page()
                page.set_default_timeout(timeout_ms)
                page.emulate_media(media="print", color_scheme="light")
                page.set_content(html, wait_until="load")
                return page.pdf(
                    format="A4",
                    print_background=False,
                    prefer_css_page_size=True,
                    display_header_footer=False,
                    margin={
                        "top": margin,
                        "right": margin,
                        "bottom": margin,
                        "left": margin,
                    },
                )
            finally:
                browser.close()
    except BrowserUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - a real browser failure
        raise SheetRenderError(f"Chromium failed to render the sheet: {exc}") from exc


def browser_available() -> bool:
    """Cheap probe so a caller (or a test) can degrade instead of failing."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
    except Exception:
        return False
    return True


# --------------------------------------------------------------------------
# 2 · storage — one function, so swapping the backend touches one place
# --------------------------------------------------------------------------
def render_dir() -> Path:
    """Where PDFs land when there is no object store yet."""
    return Path(os.environ.get(RENDER_DIR_ENV, DEFAULT_RENDER_DIR)).expanduser()


def store_pdf(payload: bytes, key: str) -> str:
    """Persist a rendered PDF and return the storage key.

    Writes through ``alppy.storage``, which is what serves the download URL the
    teacher clicks. The fallback to ``$ALPPY_RENDER_DIR`` exists only for a
    deployment with no object store configured at all.

    This used to probe for a module-level ``storage.put_object``, which has
    never existed — the interface is ``get_storage().put_bytes`` — so the probe
    always failed and every rendered PDF was written to the *worker's* local
    disk while ``Sheet.blank_pdf_key`` advertised an object-storage key. The
    job reported success and the download 404'd.
    """
    try:
        from alppy import storage as object_storage
    except ImportError:  # pragma: no cover - storage is a hard dependency
        object_storage = None  # type: ignore[assignment]

    if object_storage is not None:
        try:
            object_storage.get_storage().put_bytes(key, payload, PDF_CONTENT_TYPE)
            return key
        except Exception as exc:
            log.warning(
                "sheets.store_pdf.object_storage_failed",
                key=key,
                error=type(exc).__name__,
            )

    destination = render_dir() / key
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return key


def storage_key(sheet_id: UUID | str, name: str, *, layout_version: str = L.LAYOUT_VERSION) -> str:
    """Keys carry the layout version: an old scan must stay resolvable against
    the exact document it was printed from."""
    return f"sheets/{sheet_id}/{layout_version}/{name}"


# --------------------------------------------------------------------------
# 3 · database rows -> the plain dataclasses html.py understands
# --------------------------------------------------------------------------
def _item_from_exercise(
    exercise: Any,
    *,
    language: str,
    statement: str | None = None,
    variant: Any | None = None,
) -> Item:
    """One ``Exercise`` (optionally a per-student variant, optionally with the
    teacher's printed wording) as a plain, database-free ``Item``."""
    text = statement or (variant.statement if variant is not None else None) or exercise.statement
    options = None
    if variant is not None and variant.options:
        options = variant.options
    elif exercise.options:
        options = exercise.options

    if exercise.type is ExerciseType.TRUE_FALSE:
        answer_bool = (
            variant.answer_bool if variant is not None and variant.answer_bool is not None
            else exercise.answer_bool
        )
        answer_index = Item.true_false_index(answer_bool)
    elif exercise.type is ExerciseType.MCQ:
        answer_index = (
            variant.answer_index if variant is not None and variant.answer_index is not None
            else exercise.answer_index
        )
    else:
        answer_index = None

    return Item(
        key=str(exercise.id),
        type=exercise.type,
        statement=text,
        options=tuple(options or ()),
        answer_index=answer_index,
        answer_text=exercise.answer_text,
        language=exercise.language or language,
        ai_generated=exercise.origin is ExerciseOrigin.AI_GENERATED,
    )


def _sheet_items(sheet: Any) -> list[Item]:
    """The class-wide item list, in the teacher's order."""
    return [
        _item_from_exercise(
            si.exercise, language=sheet.language, statement=si.statement_override
        )
        for si in sorted(sheet.items, key=lambda si: si.position)
    ]


def _instance_items(db: Any, sheet: Any, instance: Any, fallback: list[Item]) -> list[Item]:
    """One student's item list. A differentiated instance carries its own plan;
    a plain class sheet reuses the sheet's list."""
    from alppy.models import Exercise, ExerciseVariant

    plan = list(instance.item_plan or [])
    if not plan:
        return fallback

    # The teacher's printed wording lives on the SheetItem, not in the plan —
    # the plan carries ids only. Without this lookup an edited statement was
    # stored, shown in the builder, and then silently dropped from the paper,
    # because every class sheet binds an item_plan per student.
    overrides = {
        str(si.exercise_id): si.statement_override
        for si in sheet.items
        if si.statement_override
    }

    items: list[Item] = []
    for entry in sorted(plan, key=lambda e: e.get("position", 0)):
        exercise_id = entry.get("exercise_id")
        if exercise_id is None:
            raise SheetRenderError(f"item_plan entry without exercise_id on {instance.id}")
        exercise = db.get(Exercise, UUID(str(exercise_id)))
        if exercise is None:
            raise SheetRenderError(f"item_plan references unknown exercise {exercise_id}")
        variant = None
        variant_id = entry.get("variant_id")
        if variant_id:
            variant = db.get(ExerciseVariant, UUID(str(variant_id)))
            if variant is None:
                raise SheetRenderError(f"item_plan references unknown variant {variant_id}")
        items.append(
            _item_from_exercise(
                exercise,
                language=sheet.language,
                # A per-student variant is its own wording and wins; otherwise
                # the teacher's edit applies.
                statement=None if variant is not None else overrides.get(str(exercise_id)),
                variant=variant,
            )
        )
    return items


def build_sheet_data(
    db: Any,
    sheet: Any,
    *,
    show_legend: bool = False,
    require_instances: bool = False,
) -> SheetData:
    """Assemble the printable document from database rows.

    Copies are ordered by student UID, never by insertion order, so re-rendering
    a sheet produces the same pile of paper in the same order."""
    from alppy.models import Class

    school_class = db.get(Class, sheet.class_id)
    if school_class is None:
        raise SheetRenderError(f"sheet {sheet.id} points at a class that no longer exists")

    base_items = _sheet_items(sheet)
    instances = sorted(sheet.instances, key=lambda i: i.student_uid)

    copies: list[Copy] = []
    if instances:
        for instance in instances:
            items = _instance_items(db, sheet, instance, base_items)
            copies.append(Copy(uid=instance.student_uid, items=tuple(items)))
    elif require_instances:
        raise SheetRenderError(
            f"sheet {sheet.id} has no instances; a differentiated batch is per student"
        )
    else:
        # No instances yet: print one personalised copy per student of the class.
        # A sheet without a per-student UID grid cannot be scanned back in, so
        # "one anonymous master to photocopy" is not an option the layout offers.
        students = sorted(school_class.students, key=lambda s: s.uid)
        if not students:
            raise SheetRenderError(
                f"class {school_class.code} has no students: nothing to print a UID for"
            )
        copies = [Copy(uid=student.uid, items=tuple(base_items)) for student in students]

    if not any(copy.items for copy in copies):
        raise SheetRenderError(f"sheet {sheet.id} has no items")

    subject = _subject_label(db, sheet)
    return SheetData(
        title=sheet.title,
        class_code=school_class.code,
        subject=subject,
        language=sheet.language,
        copies=tuple(copies),
        show_legend=show_legend,
        layout_version=L.LAYOUT_VERSION,
    )


def _subject_label(db: Any, sheet: Any) -> str:
    from alppy.models import Subject

    subject = db.get(Subject, sheet.subject_id)
    if subject is None:
        return ""
    labels = subject.labels or {}
    return str(labels.get(sheet.language) or labels.get("en") or subject.key)


def _stamp(sheet: Any, data: SheetData) -> None:
    """Record what was printed, and with which layout. A scan is always read
    against the layout version its sheet was printed with."""
    sheet.layout_version = L.LAYOUT_VERSION
    sheet.rendered_at = datetime.now(UTC)

    per_copy: dict[str, int] = {}
    for physical in physical_pages(data):
        per_copy[physical.copy.uid] = physical.copy_pages
    for instance in sheet.instances:
        if instance.student_uid in per_copy:
            instance.page_count = per_copy[instance.student_uid]


# --------------------------------------------------------------------------
# 4 · the two entry points the API layer calls
# --------------------------------------------------------------------------
def render_sheet_pdfs(db: Any, *, sheet_id: UUID) -> tuple[str, str]:
    """Render both documents for a sheet: ``(blank_key, answer_key_key)``.

    Always both. A sheet without its key is a sheet a teacher cannot correct on
    a Sunday evening, which is the whole point of the product."""
    from alppy.models import Sheet

    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetRenderError(f"no sheet {sheet_id}")

    data = build_sheet_data(db, sheet)
    blank = html_to_pdf(render_sheet_html(data, kind=SheetKind.BLANK))
    key = html_to_pdf(render_sheet_html(data, kind=SheetKind.ANSWER_KEY))

    blank_key = store_pdf(blank, storage_key(sheet.id, "blank.pdf"))
    answer_key = store_pdf(key, storage_key(sheet.id, "answer-key.pdf"))

    sheet.blank_pdf_key = blank_key
    sheet.answer_key_pdf_key = answer_key
    _stamp(sheet, data)
    db.flush()
    return (blank_key, answer_key)


def render_adaptive_batch(db: Any, *, sheet_id: UUID) -> str:
    """One PDF for a whole differentiated class — one ``.print-page`` per
    physical page, never one per student.

    The batch carries the mastery legend, because an adaptive sheet is the one
    place the teacher reads bands off paper."""
    from alppy.models import Sheet

    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetRenderError(f"no sheet {sheet_id}")

    data = build_sheet_data(db, sheet, show_legend=True, require_instances=True)
    payload = html_to_pdf(render_sheet_html(data, kind=SheetKind.BLANK))
    key = store_pdf(payload, storage_key(sheet.id, "adaptive-batch.pdf"))

    sheet.blank_pdf_key = key
    _stamp(sheet, data)
    db.flush()
    return key


__all__ = [
    "BrowserUnavailableError",
    "SheetRenderError",
    "browser_available",
    "build_sheet_data",
    "html_to_pdf",
    "render_adaptive_batch",
    "render_dir",
    "render_sheet_pdfs",
    "storage_key",
    "store_pdf",
]
