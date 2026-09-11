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

import base64
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from alppy.core.logging import get_logger
from alppy.models.enums import AnswerBoxFill, ExerciseOrigin, ExerciseType, SheetKind
from alppy.sheets import layout as L
from alppy.sheets.html import (
    Copy,
    FeedbackCopy,
    FeedbackData,
    SheetData,
    physical_pages,
    render_feedback_html,
    render_sheet_html,
)
from alppy.sheets.pagination import Figure, Item
from alppy.sheets.uid_code import canton_code, school_year_slot, sheet_nonce
from alppy.storage import StorageError, get_storage

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
@contextmanager
def _printed_page(html: str, *, timeout_ms: int) -> Iterator[Any]:
    """A headless Chromium page with the document loaded in print media.

    One place opens the browser, so the PDF and the measurement below see the
    document exactly the same way: same media, same colour scheme, same fonts.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise BrowserUnavailableError(
            f"playwright is not installed: {exc}. Install with: {INSTALL_HINT}"
        ) from exc

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
            # The faces arrive as data: URIs inside the document (fonts.css),
            # so there is no network to wait for — but decoding and applying
            # them is still asynchronous, and a page measured before they apply
            # is a page measured in the fallback. `measure_answer_boxes` records
            # millimetres the scan job later crops at, so measuring one text
            # flow and printing another is exactly the silent miscrop the
            # embedded faces exist to prevent.
            page.evaluate("document.fonts.ready")
            yield page
        finally:
            browser.close()


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
    margin = f"{L.MARGIN_MM:g}mm"
    try:
        with _printed_page(html, timeout_ms=timeout_ms) as page:
            pdf: bytes = page.pdf(
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
            return pdf
    except BrowserUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - a real browser failure
        raise SheetRenderError(f"Chromium failed to render the sheet: {exc}") from exc


# --------------------------------------------------------------------------
# 1b · where the written-answer boxes landed
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class MeasuredBox:
    """One answer box as Chromium laid it out: page millimetres of its border
    box, on the ``number``-th page of the document (1-based, document-wide)."""

    page_number: int
    item_index: int
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float


_ANSWER_BOX_MARKER: Final = 'data-answer-box="true"'

_MEASURE_JS: Final = """
(pages) => {
  const PX_PER_MM = 96 / 25.4;
  const out = [];
  pages.forEach((pg, i) => {
    // .sheet-geometry spans the whole physical sheet in both media, so a
    // rectangle relative to it is a rectangle in page millimetres.
    const geometry = pg.querySelector('.sheet-geometry') || pg;
    const origin = geometry.getBoundingClientRect();
    for (const el of pg.querySelectorAll('[data-answer-box="true"]')) {
      const r = el.getBoundingClientRect();
      const item = el.closest('[data-item-index]');
      out.push({
        page_number: i + 1,
        item_index: item ? Number(item.dataset.itemIndex) : -1,
        x_mm: (r.left - origin.left) / PX_PER_MM,
        y_mm: (r.top - origin.top) / PX_PER_MM,
        w_mm: r.width / PX_PER_MM,
        h_mm: r.height / PX_PER_MM,
      });
    }
  });
  return out;
}
"""


def measure_answer_boxes(html: str, *, timeout_ms: int = 60_000) -> list[MeasuredBox]:
    """Where every written-answer box sits on the printed page, measured from
    the same document Chromium prints, in the same print media.

    Measured rather than computed on purpose. A bubble sits where the layout
    says; a box sits under text whose wrapping only the browser knows, and
    pagination's estimate of that height is deliberately generous. The scan
    job crops at these rectangles, so they have to be the rectangles that went
    to the printer — which is why this is asked of the browser and stored,
    never derived from the rows again.

    A document with no box returns without opening a browser at all.
    """
    if _ANSWER_BOX_MARKER not in html:
        return []
    try:
        with _printed_page(html, timeout_ms=timeout_ms) as page:
            raw = page.eval_on_selector_all(".print-page", _MEASURE_JS)
    except BrowserUnavailableError:
        raise
    except Exception as exc:  # pragma: no cover - a real browser failure
        raise SheetRenderError(f"Chromium failed to measure the sheet: {exc}") from exc
    boxes = [
        MeasuredBox(
            page_number=int(b["page_number"]),
            item_index=int(b["item_index"]),
            x_mm=round(float(b["x_mm"]), 3),
            y_mm=round(float(b["y_mm"]), 3),
            w_mm=round(float(b["w_mm"]), 3),
            h_mm=round(float(b["h_mm"]), 3),
        )
        for b in raw
    ]
    for box in boxes:
        _check_box_inside_statement_region(box)
    return boxes


def _check_box_inside_statement_region(box: MeasuredBox) -> None:
    """A box outside the statement region is a geometry bug, and the crop cut
    from it could carry the header — the one region of the page with a code
    on it. Loud rather than quiet, for the same reason the PII gate raises."""
    if box.item_index < 0:
        raise SheetRenderError("an answer box was found outside any item")
    top, bottom = box.y_mm, box.y_mm + box.h_mm
    if top < L.ITEMS_TOP_MM - 0.5 or bottom > L.ITEMS_BOTTOM_MM + 0.5:
        raise SheetRenderError(
            f"answer box of item {box.item_index} on page {box.page_number} spans "
            f"{top:.1f}-{bottom:.1f} mm, outside the statement region "
            f"{L.ITEMS_TOP_MM:g}-{L.ITEMS_BOTTOM_MM:g} mm"
        )


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
    # From settings, not `os.environ` (audit 03, B25): a value the config module
    # cannot see is a value no startup check can validate.
    from alppy.core.config import get_settings

    return Path(get_settings().render_dir or DEFAULT_RENDER_DIR).expanduser()


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
    box_lines: int | None = None,
    box_fill: AnswerBoxFill | str | None = None,
    expected_answer: str | None = None,
    points_correct: float = L.DEFAULT_POINTS_CORRECT,
) -> Item:
    """One ``Exercise`` (optionally a per-student variant, optionally with the
    teacher's printed wording, answer box and expected answer) as a plain,
    database-free ``Item``. The sheet item's expected answer wins over the
    exercise's own, so the key prints what the teacher wrote for this sheet."""
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

    # A per-student variant is a rewording, and the book's picture would
    # contradict it; the picture only prints with the exercise it was cut from.
    figure = None if variant is not None else _figure_from_exercise(exercise, alt=text)
    if figure is not None and statement:
        figure = Figure(
            src=figure.src,
            width_mm=figure.width_mm,
            height_mm=figure.height_mm,
            alt=figure.alt,
            show_statement=True,
        )

    return Item(
        key=str(exercise.id),
        type=exercise.type,
        statement=text,
        options=tuple(options or ()),
        answer_index=answer_index,
        answer_text=expected_answer or exercise.answer_text,
        language=exercise.language or language,
        ai_generated=exercise.origin is ExerciseOrigin.AI_GENERATED,
        open_lines=box_lines if box_lines is not None else L.ANSWER_BOX_DEFAULT_LINES,
        box_fill=AnswerBoxFill(box_fill) if box_fill else AnswerBoxFill.LINED,
        points_correct=points_correct,
        figure=figure,
    )


def _figure_from_exercise(exercise: Any, *, alt: str) -> Figure | None:
    """The exercise's crop as a ``data:`` URI, or ``None`` when it has none.

    Inlined rather than linked: ``html_to_pdf`` loads the document from a
    string with no base URL, and the render worker has no business fetching
    from the object store over HTTP while Chromium waits. A crop that cannot be
    read is *logged and dropped*, and the item prints its text — a teacher gets
    a sheet with a gap they can see rather than no sheet at all.
    """
    key = getattr(exercise, "figure_key", None)
    width = getattr(exercise, "figure_width_mm", None)
    height = getattr(exercise, "figure_height_mm", None)
    if not key or not width or not height:
        return None
    try:
        payload = get_storage().get_bytes(key)
    except StorageError as exc:
        log.warning(
            "sheets.figure.unreadable", exercise_id=str(exercise.id), key=key, error=str(exc)
        )
        return None
    encoded = base64.b64encode(payload).decode("ascii")
    return Figure(
        src=f"data:image/png;base64,{encoded}",
        width_mm=float(width),
        height_mm=float(height),
        alt=alt,
    )


def build_draft_sheet_data(
    db: Any,
    *,
    school_id: Any,
    class_id: Any,
    subject_id: Any,
    title: str,
    language: str,
    items: Sequence[Any],
    show_legend: bool = False,
    default_points_correct: float = L.DEFAULT_POINTS_CORRECT,
) -> SheetData:
    """Assemble a printable document from a sheet that has not been saved.

    The builder needs a preview while the teacher is still reordering, and the
    alternatives are both wrong: redrawing the page in React duplicates the
    millimetre geometry `layout.py` owns and the scan detector reads, and
    creating a real draft `Sheet` writes a row plus one `SheetInstance` per
    student on every edit and leaves junk behind when the teacher walks away.

    So this takes the unsaved item list and produces the same `SheetData` that
    `build_sheet_data` produces from rows — same dataclass, same templates, same
    pagination, therefore the same page breaks and the same `ItemTooTallError`.

    One copy, not one per student: the preview answers "what does this sheet
    look like", and thirty near-identical copies would only make the teacher
    page through the class to reach page 2. The UID shown is the first student's,
    so the grid is real rather than a drawn placeholder.
    """
    from alppy.models import Class, Exercise

    school_class = db.get(Class, class_id)
    if school_class is None or school_class.school_id != school_id:
        raise SheetRenderError("this class does not exist")

    ordered = sorted(items, key=lambda i: getattr(i, "position", 0))
    built: list[Item] = []
    for entry in ordered:
        exercise = db.get(Exercise, entry.exercise_id)
        if exercise is None or exercise.school_id != school_id:
            raise SheetRenderError(f"unknown exercise {entry.exercise_id}")
        built.append(
            _item_from_exercise(
                exercise,
                language=language,
                statement=getattr(entry, "statement_override", None),
                box_lines=getattr(entry, "answer_box_lines", None),
                box_fill=getattr(entry, "answer_box_fill", None),
                expected_answer=getattr(entry, "expected_answer", None),
                # No Sheet row exists yet, so the sheet-level default arrives
                # as an argument instead of off a column.
                points_correct=(
                    float(entry.points_correct)
                    if getattr(entry, "points_correct", None) is not None
                    else default_points_correct
                ),
            )
        )
    if not built:
        raise SheetRenderError("a sheet with no items cannot be previewed")

    students = sorted(school_class.roster, key=lambda s: s.uid)
    if not students:
        raise SheetRenderError(
            f"class {school_class.code} has no students: nothing to print a UID for"
        )

    return SheetData(
        title=title or school_class.code,
        class_code=school_class.code,
        subject=_subject_label_for(db, subject_id),
        language=language,
        copies=(Copy(uid=students[0].uid, items=tuple(built)),),
        show_legend=show_legend,
        layout_version=L.LAYOUT_VERSION,
    )


def _subject_label_for(db: Any, subject_id: Any) -> str:
    from alppy.models import Subject

    subject = db.get(Subject, subject_id)
    if subject is None:
        return ""
    labels = getattr(subject, "labels", None) or {}
    if isinstance(labels, dict) and labels:
        return str(labels.get("fr") or labels.get("de") or labels.get("en") or subject.key)
    return str(subject.key)


def _points_for(item: Any, sheet: Any) -> float:
    """What one item is worth: its own override, else the sheet's default.

    ``is not None`` rather than ``or``: 0 is a real choice — an item that earns
    nothing — and reading it as absent would hand the item the default back.
    """
    override = getattr(item, "points_correct", None)
    if override is not None:
        return float(override)
    return float(getattr(sheet, "default_points_correct", L.DEFAULT_POINTS_CORRECT))


def _sheet_items(sheet: Any) -> list[Item]:
    """The class-wide item list, in the teacher's order."""
    return [
        _item_from_exercise(
            si.exercise,
            language=sheet.language,
            statement=si.statement_override,
            box_lines=si.answer_box_lines,
            box_fill=si.answer_box_fill,
            expected_answer=si.expected_answer,
            points_correct=_points_for(si, sheet),
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
    # The answer box is the teacher's choice too, and a variant is a rewording
    # of the same question: the box follows the sheet item either way.
    boxes = {str(si.exercise_id): si for si in sheet.items}

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
                box_lines=getattr(boxes.get(str(exercise_id)), "answer_box_lines", None),
                box_fill=getattr(boxes.get(str(exercise_id)), "answer_box_fill", None),
                # The teacher's expected answer follows the sheet item, like
                # the box; a variant is a rewording of the same question.
                expected_answer=getattr(boxes.get(str(exercise_id)), "expected_answer", None),
                # Through the same lookup as the box, and for the same reason:
                # a plan carries ids, so an override not fetched here is
                # silently dropped from every differentiated copy.
                points_correct=_points_for(boxes.get(str(exercise_id)), sheet),
            )
        )
    return items


def _open_render_generation(sheet: Any) -> int:
    """Start a new render generation, before anything is laid out.

    Before `build_sheet_data`, because layout v2 prints the generation into the
    UID grid (as half of the nonce) and the answer-box rectangles are filed
    under it: bumping afterwards would put generation N on the paper and N+1 in
    the database, which is precisely the disagreement B7 exists to end.
    """
    sheet.render_generation = (sheet.render_generation or 0) + 1
    return int(sheet.render_generation)


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
        students = sorted(school_class.roster, key=lambda s: s.uid)
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
        # What layout v2 prints beyond the pupil (B4). Computed here rather
        # than in `html.py`, which takes no database: the nonce needs the
        # sheet's id and render generation, the year slot needs the class's
        # SchoolYear, and the canton needs the School.
        nonce=sheet_nonce(sheet.id, sheet.render_generation or 0),
        school_year_slot=_school_year_slot_for(db, school_class),
        canton=_canton_for(db, sheet),
    )


def _school_year_slot_for(db: Any, school_class: Any) -> int:
    from alppy.models import SchoolYear

    year = db.get(SchoolYear, school_class.school_year_id)
    if year is None or year.starts_on is None:  # pragma: no cover - NOT NULL
        return 0
    return school_year_slot(year.starts_on.year)


def _canton_for(db: Any, sheet: Any) -> int:
    from alppy.models import School

    school = db.get(School, sheet.school_id)
    return canton_code(school.canton if school is not None else None)


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


def _persist_answer_box_placements(
    db: Any, sheet: Any, data: SheetData, boxes: Sequence[MeasuredBox]
) -> int:
    """Record where every box printed, as a new generation of this sheet.

    Delete-then-insert, never upsert by student: a re-render after a roster
    change must lose the rows of a child who left as surely as it gains the
    rows of one who arrived. That reasoning is correct and is kept — but it is
    kept **inside one generation** (B7).

    Before, the delete was by sheet, so every re-render destroyed the
    rectangles that already-printed copies had been measured at. Print on
    Tuesday, re-render on Wednesday for an absentee, photograph Tuesday's
    copies on Thursday, and all of them are cropped at Wednesday's geometry.
    The row that would have said so had been deleted on Wednesday.

    The generation is bumped by `_open_render_generation` **before**
    `build_sheet_data` runs, not here, and the ordering is load-bearing since
    B4: layout v2 prints the generation into the UID grid as part of the nonce,
    so a bump after the document was built would print one generation on the
    paper and file the rectangles under the next. The delete below then matches
    only rows of the generation being written — a no-op except on a render
    retried after a partial write, which is the case it still covers. Earlier
    generations stay exactly where they are, because a pile printed from them
    may not have been photographed yet.

    Returns how many were written.
    """
    from sqlalchemy import delete

    from alppy.models import AnswerBoxPlacement

    generation = sheet.render_generation or 0
    db.execute(
        delete(AnswerBoxPlacement)
        .where(AnswerBoxPlacement.sheet_id == sheet.id)
        .where(AnswerBoxPlacement.render_generation == generation)
    )
    pages = physical_pages(data)
    written = 0
    for box in boxes:
        physical = pages[box.page_number - 1]
        placed = physical.page.items[box.item_index]
        try:
            exercise_id: uuid.UUID | None = UUID(placed.item.key)
        except ValueError:
            exercise_id = None
        db.add(
            AnswerBoxPlacement(
                id=uuid.uuid4(),
                school_id=sheet.school_id,
                sheet_id=sheet.id,
                render_generation=generation,
                exercise_id=exercise_id,
                student_uid=physical.copy.uid,
                copy_page=physical.copy_page,
                item_index=box.item_index,
                box_lines=placed.item.open_lines,
                box_fill=placed.item.box_fill,
                x_mm=box.x_mm,
                y_mm=box.y_mm,
                w_mm=box.w_mm,
                h_mm=box.h_mm,
                layout_version=L.LAYOUT_VERSION,
            )
        )
        written += 1
    db.flush()
    return written


# --------------------------------------------------------------------------
# 4 · the two entry points the API layer calls
# --------------------------------------------------------------------------
def _refuse_unapproved(sheet: Any) -> None:
    """No AI-generated exercise reaches paper without a teacher's approval.

    Checked here, in the render path, and not only where the sheet was built:
    a sheet can be re-rendered long after it was assembled, and an exercise can
    be un-approved (or discarded) in between. This is the last door, so it is
    the one that has to be locked.
    """
    from alppy.services.approval import UnapprovedExerciseError, ensure_printable

    try:
        ensure_printable(item.exercise for item in sheet.items)
    except UnapprovedExerciseError as exc:
        raise SheetRenderError(str(exc)) from exc


def render_sheet_pdfs(db: Any, *, sheet_id: UUID) -> tuple[str, str]:
    """Render both documents for a sheet: ``(blank_key, answer_key_key)``.

    Always both. A sheet without its key is a sheet a teacher cannot correct on
    a Sunday evening, which is the whole point of the product."""
    from alppy.models import Sheet

    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetRenderError(f"no sheet {sheet_id}")

    _refuse_unapproved(sheet)

    # Before the document is built: v2 prints the generation into the grid.
    _open_render_generation(sheet)
    data = build_sheet_data(db, sheet)
    blank_html = render_sheet_html(data, kind=SheetKind.BLANK)
    blank = html_to_pdf(blank_html)
    key = html_to_pdf(render_sheet_html(data, kind=SheetKind.ANSWER_KEY))

    blank_key = store_pdf(blank, storage_key(sheet.id, "blank.pdf"))
    answer_key = store_pdf(key, storage_key(sheet.id, "answer-key.pdf"))

    sheet.blank_pdf_key = blank_key
    sheet.answer_key_pdf_key = answer_key
    _stamp(sheet, data)
    # The blank is what the students write on, so its boxes are the ones the
    # scanner will crop. Measured from the same document that became the PDF.
    _persist_answer_box_placements(db, sheet, data, measure_answer_boxes(blank_html))
    db.flush()
    return (blank_key, answer_key)


def build_feedback_data(db: Any, sheet: Any) -> FeedbackData | None:
    """The feedback pages for one adaptive batch, or None if there are none.

    Only APPROVED, non-discarded notes reach this. A note the teacher has not
    read yet simply produces no page — the gate above raises for a batch that
    references one, so silence here means "this student had nothing to be
    told", which is a real and common outcome.
    """
    from alppy.models import Class

    school_class = db.get(Class, sheet.class_id)
    if school_class is None:
        raise SheetRenderError(f"sheet {sheet.id} points at a class that no longer exists")

    copies: list[FeedbackCopy] = []
    for instance in sorted(sheet.instances, key=lambda i: i.student_uid):
        note = instance.feedback
        if note is None or note.approved_at is None or note.discarded_at is not None:
            continue
        notes = tuple(str(n) for n in (note.notes or []) if str(n).strip())
        if not notes:
            continue
        copies.append(
            FeedbackCopy(
                uid=instance.student_uid,
                notes=notes,
                group_label=instance.group_label,
            )
        )
    if not copies:
        return None

    source_title = None
    if sheet.derived_from_id is not None:
        from alppy.models import Sheet as SheetModel

        source = db.get(SheetModel, sheet.derived_from_id)
        source_title = source.title if source is not None else None

    return FeedbackData(
        title=sheet.title,
        class_code=school_class.code,
        subject=_subject_label(db, sheet),
        language=sheet.language,
        copies=tuple(copies),
        # DD.MM.YYYY reads the same in fr, de and en-CH, so this needs no
        # locale table — unlike a month name, which would.
        date_label=sheet.created_at.strftime("%d.%m.%Y") if sheet.created_at else None,
        source_title=source_title,
    )


def render_feedback_pdf(db: Any, *, sheet_id: UUID) -> str | None:
    """The third document: one feedback page per student who has a note.

    Separate from the blank and the key by design, not by convenience — see
    `html.FeedbackData` for the misgrading this prevents.
    """
    from alppy.models import Sheet

    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetRenderError(f"no sheet {sheet_id}")

    data = build_feedback_data(db, sheet)
    if data is None:
        sheet.feedback_pdf_key = None
        db.flush()
        return None

    pdf = html_to_pdf(render_feedback_html(data))
    key = store_pdf(pdf, storage_key(sheet.id, "feedback.pdf"))
    sheet.feedback_pdf_key = key
    db.flush()
    return key


def render_adaptive_batch(db: Any, *, sheet_id: UUID) -> tuple[str, str]:
    """One PDF for a whole differentiated class, plus its answer key.

    One ``.print-page`` per physical page, never one per student. Always both
    documents: a differentiated pile is the case where a teacher *cannot*
    correct from memory, because no two children answered the same questions.
    The key is rendered from the same `SheetData`, so the copies come out in the
    same order as the blanks and the piles line up.

    The batch carries the mastery legend, because an adaptive sheet is the one
    place the teacher reads bands off paper."""
    from alppy.models import Sheet

    sheet = db.get(Sheet, sheet_id)
    if sheet is None:
        raise SheetRenderError(f"no sheet {sheet_id}")

    _refuse_unapproved(sheet)

    _open_render_generation(sheet)
    data = build_sheet_data(db, sheet, show_legend=True, require_instances=True)
    blank_html = render_sheet_html(data, kind=SheetKind.BLANK)
    blank = html_to_pdf(blank_html)
    key = html_to_pdf(render_sheet_html(data, kind=SheetKind.ANSWER_KEY))

    blank_key = store_pdf(blank, storage_key(sheet.id, "adaptive-batch.pdf"))
    answer_key = store_pdf(key, storage_key(sheet.id, "adaptive-batch-answer-key.pdf"))

    sheet.blank_pdf_key = blank_key
    sheet.answer_key_pdf_key = answer_key
    _stamp(sheet, data)
    _persist_answer_box_placements(db, sheet, data, measure_answer_boxes(blank_html))

    # The feedback pages, as their own document. `_stamp` has already recorded
    # `page_count` from the graded pagination above, and this cannot touch it.
    feedback = build_feedback_data(db, sheet)
    sheet.feedback_pdf_key = (
        store_pdf(html_to_pdf(render_feedback_html(feedback)), storage_key(sheet.id, "feedback.pdf"))
        if feedback is not None
        else None
    )
    db.flush()
    return (blank_key, answer_key)


__all__ = [
    "BrowserUnavailableError",
    "MeasuredBox",
    "SheetRenderError",
    "browser_available",
    "build_sheet_data",
    "html_to_pdf",
    "measure_answer_boxes",
    "render_adaptive_batch",
    "render_dir",
    "render_sheet_pdfs",
    "storage_key",
    "store_pdf",
]
