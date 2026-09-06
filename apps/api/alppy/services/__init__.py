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
from typing import Any

from alppy.models import (
    Chapter,
    Class,
    Competency,
    Detection,
    Exercise,
    Job,
    Scan,
    ScanPage,
    Sheet,
    SheetInstance,
    SheetItem,
    Source,
    Student,
    Subject,
    Teacher,
)
from alppy.schemas import (
    ChapterOut,
    ClassOut,
    CompetencyOut,
    DetectionOut,
    ExerciseOut,
    JobOut,
    ScanOut,
    ScanPageOut,
    SheetInstanceOut,
    SheetItemOut,
    SheetOut,
    SourceOut,
    StudentOut,
    SubjectOut,
    TeacherOut,
    TeacherPreferences,
)
from alppy.storage import Storage

__all__ = [
    "chapter_out",
    "class_out",
    "competency_out",
    "detection_out",
    "exercise_out",
    "job_out",
    "scan_out",
    "scan_page_out",
    "sheet_instance_out",
    "sheet_item_out",
    "sheet_out",
    "source_out",
    "student_out",
    "subject_out",
    "teacher_out",
]


def teacher_out(teacher: Teacher) -> TeacherOut:
    return TeacherOut(
        id=teacher.id,
        email=teacher.email,
        first_name=teacher.first_name,
        last_name=teacher.last_name,
        school_id=teacher.school_id,
        preferences=TeacherPreferences(
            locale=str(teacher.locale),
            theme=teacher.theme,
            contrast=teacher.contrast,
            motion=teacher.motion,
            calm=teacher.calm,
        ),
    )


def student_out(student: Student) -> StudentOut:
    return StudentOut(
        id=student.id,
        uid=student.uid,
        number=student.number,
        first_name=student.first_name,
        last_name=student.last_name,
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
        source_page=exercise.source_page,
        approved_at=exercise.approved_at,
    )


def source_out(source: Source, *, exercise_count: int = 0) -> SourceOut:
    return SourceOut(
        id=source.id,
        filename=source.filename,
        content_type=source.content_type,
        size_bytes=source.size_bytes,
        language=source.language,
        page_count=source.page_count,
        status=source.status,
        error=source.error,
        notice=source.notice,
        exercise_count=exercise_count,
        created_at=source.created_at,
    )


def sheet_item_out(item: SheetItem) -> SheetItemOut:
    return SheetItemOut(
        id=item.id,
        position=item.position,
        statement_override=item.statement_override,
        exercise=exercise_out(item.exercise),
    )


def sheet_instance_out(instance: SheetInstance) -> SheetInstanceOut:
    return SheetInstanceOut(
        id=instance.id,
        student_id=instance.student_id,
        student_uid=instance.student_uid,
        page_count=instance.page_count,
    )


def _url(storage: Storage | None, key: str | None) -> str | None:
    if storage is None or not key:
        return None
    return storage.url_for(key)


def sheet_out(sheet: Sheet, *, storage: Storage | None = None) -> SheetOut:
    return SheetOut(
        id=sheet.id,
        class_id=sheet.class_id,
        subject_id=sheet.subject_id,
        title=sheet.title,
        target=sheet.target,
        language=sheet.language,
        intent=sheet.intent,
        layout_version=sheet.layout_version,
        items=[sheet_item_out(i) for i in sorted(sheet.items, key=lambda i: i.position)],
        instances=[sheet_instance_out(i) for i in sheet.instances],
        blank_pdf_url=_url(storage, sheet.blank_pdf_key),
        answer_key_pdf_url=_url(storage, sheet.answer_key_pdf_key),
        rendered_at=sheet.rendered_at,
        created_at=sheet.created_at,
    )


def detection_out(detection: Detection) -> DetectionOut:
    return DetectionOut(
        id=detection.id,
        item_index=detection.item_index,
        sheet_item_id=detection.sheet_item_id,
        detected_index=detection.detected_index,
        detected_bool=detection.detected_bool,
        confidence=detection.confidence,
        outcome=detection.outcome,
        fill_ratios=list(detection.fill_ratios) if detection.fill_ratios else None,
        bubble_boxes=[dict(b) for b in detection.bubble_boxes] if detection.bubble_boxes else None,
        corrected_at=detection.corrected_at,
    )


def scan_page_out(page: ScanPage, *, storage: Storage | None = None) -> ScanPageOut:
    return ScanPageOut(
        id=page.id,
        page_index=page.page_index,
        image_url=_url(storage, page.image_key),
        registered=page.registered,
        detected_uid=page.detected_uid,
        uid_confidence=page.uid_confidence,
        student_id=page.student_id,
        sheet_instance_id=page.sheet_instance_id,
        detections=[
            detection_out(d) for d in sorted(page.detections, key=lambda d: d.item_index)
        ],
    )


def scan_out(scan: Scan, *, storage: Storage | None = None) -> ScanOut:
    return ScanOut(
        id=scan.id,
        sheet_id=scan.sheet_id,
        original_filename=scan.original_filename,
        status=scan.status,
        error=scan.error,
        pages=[scan_page_out(p, storage=storage) for p in scan.pages],
        created_at=scan.created_at,
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
