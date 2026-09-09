"""Service layer.

Routers stay thin: they authenticate, resolve the tenant, validate the request
and hand off. Everything that knows about the domain — how a roster becomes
UIDs, how a confirmed scan becomes attempts, how attempts become bands — lives
here and takes ``school_id`` as a required argument.

This module holds the ORM-to-schema serialisers the routers share. They are
explicit rather than ``from_attributes``: several response fields (a class's
student count, an exercise's competency ids, a signed storage URL) are not
attributes of the row.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from alppy.models import (
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
    Job,
    Scan,
    ScanPage,
    School,
    Sheet,
    SheetInstance,
    SheetItem,
    Source,
    SourceSection,
    Student,
    Subject,
    Teacher,
)
from alppy.models.enums import ExerciseOrigin, ExerciseType
from alppy.schemas import (
    ChapterOut,
    ClassOut,
    ClassPointsOut,
    ClassSheetPointsOut,
    CompetencyOut,
    DetectionOut,
    ExerciseOut,
    ItemConfidenceOut,
    JobOut,
    ScanOut,
    ScanPageOut,
    SchoolOut,
    SheetConfidenceOut,
    SheetInstanceOut,
    SheetItemOut,
    SheetOut,
    SheetScanOut,
    SourceOut,
    SourceSectionOut,
    StudentOut,
    StudentPointsOut,
    StudentSheetItemOut,
    StudentSheetOut,
    SubjectOut,
    TeacherOut,
    TeacherPreferences,
)
from alppy.sheets.layout import OptionLetters, tf_letters
from alppy.storage import Storage, get_storage

if TYPE_CHECKING:
    from alppy.services.results_service import StudentSheet
    from alppy.services.scan_service import ItemConfidence

    # Guarded: `sheet_service` imports this package (for `event_service`), so
    # importing it back at runtime would close the cycle. `from __future__
    # import annotations` makes the annotation a string, so the guard is
    # enough — nothing here needs the class at runtime.
    from alppy.services.sheet_service import ClassPointsReport, SheetPoints

__all__ = [
    "chapter_out",
    "class_out",
    "competency_out",
    "detection_out",
    "exercise_out",
    "job_out",
    "scan_out",
    "scan_page_out",
    "school_out",
    "sheet_instance_out",
    "sheet_item_out",
    "sheet_out",
    "source_out",
    "source_section_out",
    "student_out",
    "subject_out",
    "teacher_out",
]


def school_out(school: School) -> SchoolOut:
    return SchoolOut(
        id=school.id,
        name=school.name,
        canton=school.canton,
        default_curriculum=school.default_curriculum,
    )


def teacher_out(
    teacher: Teacher, school_id: uuid.UUID, *, schools: list[School] | None = None
) -> TeacherOut:
    """The signed-in teacher, reported for ONE school.

    ``school_id`` is passed rather than read off the row because since D74 a
    teacher may work at several and the row only knows where they are based.
    The client switches tenants on this field, so reporting
    ``home_school_id`` here would have every screen quietly describe the wrong
    school the moment somebody switched (I-platform-14).
    """
    return TeacherOut(
        id=teacher.id,
        email=teacher.email,
        first_name=teacher.first_name,
        last_name=teacher.last_name,
        school_id=school_id,
        schools=[school_out(s) for s in (schools or [])],
        preferences=TeacherPreferences(
            locale=str(teacher.locale),
            theme=teacher.theme,
            contrast=teacher.contrast,
            motion=teacher.motion,
            calm=teacher.calm,
        ),
    )


def student_out(student: Student) -> StudentOut:
    home = student.home_class.code
    # Home first, then the rest in code order. A roster reads the first chip as
    # "whose pupil this is" and the others as "and also sits here", so the
    # order is part of the meaning rather than a display detail.
    others = sorted(c.code for c in student.classes if c.code != home)
    return StudentOut(
        id=student.id,
        uid=student.uid,
        number=student.number,
        first_name=student.first_name,
        last_name=student.last_name,
        home_class_code=home,
        class_codes=[home, *others],
    )


def class_out(
    school_class: Class, *, student_count: int = 0, subject_ids: list[uuid.UUID] | None = None
) -> ClassOut:
    return ClassOut(
        id=school_class.id,
        code=school_class.code,
        label=school_class.label,
        student_count=student_count,
        subject_ids=subject_ids or [],
    )


def subject_out(subject: Subject) -> SubjectOut:
    return SubjectOut(id=subject.id, key=subject.key, labels=dict(subject.labels or {}))


def competency_out(competency: Competency) -> CompetencyOut:
    return CompetencyOut(
        id=competency.id,
        curriculum=competency.curriculum,
        code=competency.code,
        parent_id=competency.parent_id,
        subject_key=competency.subject_key,
        cycle=competency.cycle,
        labels=dict(competency.labels or {}),
        description=dict(competency.description or {}),
    )


def chapter_out(chapter: Chapter) -> ChapterOut:
    return ChapterOut(
        id=chapter.id,
        key=chapter.key,
        labels=dict(chapter.labels or {}),
        position=chapter.position,
        competency_ids=[c.id for c in chapter.competencies],
        primary_competency_id=chapter.primary_competency_id,
    )


def exercise_out(exercise: Exercise) -> ExerciseOut:
    return ExerciseOut(
        id=exercise.id,
        type=exercise.type,
        origin=exercise.origin,
        language=exercise.language,
        statement=exercise.statement,
        options=list(exercise.options) if exercise.options else None,
        answer_index=exercise.answer_index,
        answer_bool=exercise.answer_bool,
        answer_text=exercise.answer_text,
        explanation=exercise.explanation,
        difficulty=exercise.difficulty,
        chapter_id=exercise.chapter_id,
        competency_ids=[c.id for c in exercise.competencies],
        source_id=exercise.source_id,
        source_section_id=exercise.source_section_id,
        source_page=exercise.source_page,
        label=exercise.label,
        title=exercise.title,
        figure_url=figure_url_for(exercise),
        figure_width_mm=exercise.figure_width_mm,
        figure_height_mm=exercise.figure_height_mm,
        approved_at=exercise.approved_at,
    )


def figure_url_for(exercise: Exercise) -> str | None:
    """Where the web app fetches the exercise's crop, or ``None``.

    The local backend answers with the ``/api/v1/files/...`` route, which is
    tenant-checked; the S3 backend hands out a presigned URL. Either way the
    key itself never reaches the browser as something it could rewrite.
    """
    if not exercise.figure_key:
        return None
    return get_storage().url_for(exercise.figure_key)


def source_section_out(section: SourceSection, *, exercise_count: int = 0) -> SourceSectionOut:
    return SourceSectionOut(
        id=section.id,
        title=section.title,
        label=section.label,
        page_from=section.page_from,
        page_to=section.page_to,
        position=section.position,
        exercise_count=exercise_count,
        extracted_at=section.extracted_at,
        extraction_notice=section.extraction_notice,
    )


def source_out(source: Source, *, exercise_count: int = 0, section_count: int = 0) -> SourceOut:
    return SourceOut(
        id=source.id,
        subject_id=source.subject_id,
        filename=source.filename,
        title=source.title,
        publisher=source.publisher,
        isbn=source.isbn,
        url=source.url,
        content_type=source.content_type,
        size_bytes=source.size_bytes,
        language=source.language,
        page_count=source.page_count,
        status=source.status,
        error=source.error,
        notice=source.notice,
        exercise_count=exercise_count,
        section_count=section_count,
        created_at=source.created_at,
    )


def sheet_item_out(item: SheetItem) -> SheetItemOut:
    return SheetItemOut(
        id=item.id,
        position=item.position,
        statement_override=item.statement_override,
        answer_box_lines=item.answer_box_lines,
        answer_box_fill=item.answer_box_fill,
        expected_answer=item.expected_answer,
        points_correct=item.points_correct,
        points_penalty=item.points_penalty,
        exercise=exercise_out(item.exercise),
    )


def sheet_instance_out(
    instance: SheetInstance, points: SheetPoints | None = None
) -> SheetInstanceOut:
    return SheetInstanceOut(
        id=instance.id,
        student_id=instance.student_id,
        student_uid=instance.student_uid,
        page_count=instance.page_count,
        group_label=instance.group_label,
        has_feedback=instance.feedback_id is not None,
        points_earned=points.earned if points is not None else None,
        points_possible=points.possible if points is not None else 0.0,
    )


def _url(storage: Storage | None, key: str | None) -> str | None:
    if storage is None or not key:
        return None
    return storage.url_for(key)


def sheet_out(
    sheet: Sheet,
    *,
    storage: Storage | None = None,
    points: Mapping[uuid.UUID, SheetPoints] | None = None,
) -> SheetOut:
    """Serialise a sheet. Pure: the marks are computed by the caller (see
    ``sheet_service.points_totals_for_sheet``) and handed in, so this stays a
    function of its arguments rather than one that queries."""
    return SheetOut(
        id=sheet.id,
        class_id=sheet.class_id,
        subject_id=sheet.subject_id,
        chapter_id=sheet.chapter_id,
        title=sheet.title,
        target=sheet.target,
        language=sheet.language,
        intent=sheet.intent,
        layout_version=sheet.layout_version,
        default_points_correct=sheet.default_points_correct,
        default_points_penalty=sheet.default_points_penalty,
        items=[sheet_item_out(i) for i in sorted(sheet.items, key=lambda i: i.position)],
        instances=[
            sheet_instance_out(i, points.get(i.student_id) if points else None)
            for i in sheet.instances
        ],
        blank_pdf_url=_url(storage, sheet.blank_pdf_key),
        answer_key_pdf_url=_url(storage, sheet.answer_key_pdf_key),
        feedback_pdf_url=_url(storage, sheet.feedback_pdf_key),
        derived_from_id=sheet.derived_from_id,
        source_sheet_ids=[s.id for s in sheet.sources],
        scans=[
            SheetScanOut(
                id=scan.id,
                status=scan.status,
                revised=scan.confirmation_count > 1,
                confirmed_at=scan.confirmed_at,
                reopened_at=scan.reopened_at,
                created_at=scan.created_at,
            )
            for scan in sheet.scans
        ],
        # Derived from the items, never stored: a `sheet_competency` table
        # would have to be rewritten on every edit and could then disagree with
        # the items it claims to describe. Distinct from `chapter_id` above,
        # which is the one home Theme the teacher stated (I-sheets-11).
        competency_ids=sorted(
            {c.id for i in sheet.items for c in i.exercise.competencies}, key=str
        ),
        chapter_ids=sorted(
            {i.exercise.chapter_id for i in sheet.items if i.exercise.chapter_id is not None},
            key=str,
        ),
        rendered_at=sheet.rendered_at,
        created_at=sheet.created_at,
    )


def detection_out(
    detection: Detection, *, language: str = "fr", storage: Storage | None = None
) -> DetectionOut:
    """One reading, with the question it is a reading *of*.

    The statement and the option letters travel with the detection because the
    review screen is where a teacher adjudicates a mark the machine was unsure
    about, and "#7, low confidence, A/B/C/D" is not something anyone can
    adjudicate. The letters come from the layout so a true/false item shows
    V/F (or R/F, T/F) — the glyphs the student actually saw on the paper.
    """
    exercise = detection.exercise
    options: list[str] | None = None
    letters: str | None = None
    answer_index: int | None = None
    if exercise is not None:
        if exercise.type is ExerciseType.TRUE_FALSE:
            letters = tf_letters(exercise.language or language)
            # Bubble 0 is "true" in every sheet language; the glyph changes,
            # the position never does.
            if exercise.answer_bool is not None:
                answer_index = 0 if exercise.answer_bool else 1
        elif exercise.type is ExerciseType.MCQ:
            options = list(exercise.options or [])
            letters = OptionLetters.MCQ.value[: exercise.option_count]
            answer_index = exercise.answer_index

    return DetectionOut(
        id=detection.id,
        item_index=detection.item_index,
        number=detection.printed_number,
        sheet_item_id=detection.sheet_item_id,
        exercise_id=detection.exercise_id,
        detected_index=detection.detected_index,
        detected_bool=detection.detected_bool,
        confidence=detection.confidence,
        outcome=detection.outcome,
        fill_ratios=list(detection.fill_ratios) if detection.fill_ratios else None,
        bubble_boxes=[dict(b) for b in detection.bubble_boxes] if detection.bubble_boxes else None,
        corrected_at=detection.corrected_at,
        machine_index=detection.machine_index,
        machine_outcome=detection.machine_outcome,
        machine_confidence=detection.machine_confidence,
        statement=exercise.statement if exercise is not None else None,
        options=options,
        option_letters=letters,
        exercise_type=exercise.type if exercise is not None else None,
        ai_generated=(exercise is not None and exercise.origin is ExerciseOrigin.AI_GENERATED),
        answer_index=answer_index,
        crop_url=_url(storage, detection.crop_key),
        transcription=detection.transcription,
        verdict_correct=detection.verdict_correct,
        machine_transcription=detection.machine_transcription,
        machine_verdict_correct=detection.machine_verdict_correct,
        vision_model=detection.vision_model,
        answer_text=expected_answer_for(detection),
        reference_answer=(
            detection.reference_answer if expected_answer_for(detection) is None else None
        ),
    )


def expected_answer_for(detection: Detection) -> str | None:
    """The answer an open item is judged against: the sheet item's, written by
    the teacher for this printing, else the exercise's own. ``None`` means the
    grader had to work it out itself."""
    exercise = detection.exercise
    if exercise is None or exercise.type is not ExerciseType.OPEN:
        return None
    item = detection.sheet_item
    if item is not None and item.expected_answer:
        return item.expected_answer
    return exercise.answer_text or None


def scan_page_out(page: ScanPage, *, storage: Storage | None = None) -> ScanPageOut:
    meta = page.registration_meta or {}
    return ScanPageOut(
        id=page.id,
        page_index=page.page_index,
        image_url=_url(storage, page.image_key),
        registered=page.registered,
        detected_uid=page.detected_uid,
        uid_confidence=page.uid_confidence,
        student_id=page.student_id,
        sheet_instance_id=page.sheet_instance_id,
        wrong_class=page.wrong_class,
        discarded=page.discarded,
        page_in_copy=page.page_in_copy,
        registration_error=meta.get("error"),
        detections=[
            detection_out(d, storage=storage)
            for d in sorted(page.detections, key=lambda d: d.item_index)
        ],
    )


def scan_out(
    scan: Scan, *, storage: Storage | None = None, job_id: uuid.UUID | None = None
) -> ScanOut:
    return ScanOut(
        job_id=job_id,
        id=scan.id,
        sheet_id=scan.sheet_id,
        original_filename=scan.original_filename,
        status=scan.status,
        error=scan.error,
        pages=[scan_page_out(p, storage=storage) for p in scan.pages],
        # Derived, not stored: a pile signed off more than once has been
        # revised. Keeping this out of `status` is what stops every
        # "is it confirmed?" check in the codebase from needing to know (D48).
        revised=scan.confirmation_count > 1,
        reopened_at=scan.reopened_at,
        confirmed_at=scan.confirmed_at,
        created_at=scan.created_at,
    )


def class_points_out(class_id: uuid.UUID, report: ClassPointsReport) -> ClassPointsOut:
    """Pure: the caller computes the report, this only shapes it."""
    return ClassPointsOut(
        class_id=class_id,
        students=[
            StudentPointsOut(
                student_id=student_id, points_earned=p.earned, points_possible=p.possible
            )
            for student_id, p in report.students.items()
        ],
        sheets=[
            ClassSheetPointsOut(
                sheet_id=sheet.sheet_id,
                sheet_title=sheet.sheet_title,
                average_ratio=sheet.average_ratio,
                students=[
                    StudentPointsOut(
                        student_id=student_id,
                        points_earned=p.earned,
                        points_possible=p.possible,
                    )
                    for student_id, p in sheet.per_student.items()
                ],
            )
            for sheet in report.sheets
        ],
    )


def student_sheet_out(
    breakdown: StudentSheet, *, storage: Storage | None = None
) -> StudentSheetOut:
    return StudentSheetOut(
        student=student_out(breakdown.student),
        sheet_id=breakdown.sheet.id,
        sheet_title=breakdown.sheet.title,
        scan_id=breakdown.scan_id,
        answered_at=breakdown.answered_at,
        points_earned=breakdown.points_earned,
        points_possible=breakdown.points_possible,
        items=[
            StudentSheetItemOut(
                position=item.position,
                number=item.number,
                exercise_id=item.exercise_id,
                statement=item.statement,
                exercise_type=item.exercise_type,
                ai_generated=item.ai_generated,
                options=item.options,
                given=item.given,
                given_index=item.given_index,
                expected=item.expected,
                expected_index=item.expected_index,
                outcome=item.outcome,
                confidence=item.confidence,
                correct=item.correct,
                points_earned=item.points_earned,
                points_possible=item.points_possible,
                crop_url=_url(storage, item.crop_key),
            )
            for item in breakdown.items
        ],
    )


def sheet_confidence_out(
    sheet_id: uuid.UUID, items: Sequence[ItemConfidence]
) -> SheetConfidenceOut:
    return SheetConfidenceOut(
        sheet_id=sheet_id,
        items=[
            ItemConfidenceOut(
                sheet_item_id=item.sheet_item_id,
                exercise_id=item.exercise_id,
                number=item.number,
                statement=item.statement,
                copies_read=item.copies_read,
                low_confidence=item.low_confidence,
                ambiguous=item.ambiguous,
                corrected=item.corrected,
            )
            for item in items
        ],
    )


def job_out(job: Job) -> JobOut:
    result: dict[str, Any] | None = dict(job.result) if job.result else None
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        message=job.message,
        result=result,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )
