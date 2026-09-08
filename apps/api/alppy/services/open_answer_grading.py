"""The vision grader over a scan's written answers.

Runs as its own job, chained by the worker after ``PROCESS_SCAN``, so the
review opens the moment the marks are read and the verdicts arrive while the
teacher is already looking. One model call per pending box; each row is
committed as it lands, so a crash halfway keeps what was graded.

Three rules, in order of importance:

1. **Nothing stays ``PENDING``.** A call that fails, a provider that cannot
   see, an answer the model cannot read — every one of those lands as
   ``NOT_GRADEABLE``. A pending row is a promise; a provider that is down
   must not be allowed to keep it forever, and the grader treats a pending
   row as ungradeable in any case, so confirmation is never blocked.
2. **The offline provider grades nothing.** ``AiClient.chat_is_grounded`` is
   false for the echo stand-in, and every box is marked ungradeable without
   a call — the same refusal ingestion makes for a page of a real book.
3. **The machine's verdict is written once.** ``machine_transcription`` and
   ``machine_verdict_correct`` are set here and never again; a teacher's
   correction goes beside them.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from alppy.ai.audit import record_calls
from alppy.ai.base import ImagePart
from alppy.ai.client import AiClient, load_prompt, parse_json_response
from alppy.core.logging import get_logger
from alppy.models import AnswerBoxPlacement, Detection, Exercise, Job, Scan, ScanPage
from alppy.models.enums import DetectionOutcome, JobKind, JobStatus
from alppy.scan.detector import LOW_CONFIDENCE
from alppy.storage import Storage

log = get_logger(__name__)

ProgressCB = Callable[[float, "str | None"], None]

PROMPT_NAME = "grade_open_answer"
PROMPT_VERSION = "v1"

_FILL_WORDS = {
    "lined": "faint horizontal guide lines every 8 mm",
    "grid": "a faint 5 mm square grid",
    "blank": "no printed guides",
}


def pending_detections(db: Session, scan_id: uuid.UUID) -> list[tuple[Detection, Exercise]]:
    """Every written answer of this scan still waiting for a verdict, with the
    exercise it answers. Discarded pages and pages from another class are not
    part of the pile and are not graded."""
    rows = db.execute(
        select(Detection, Exercise)
        .join(ScanPage, ScanPage.id == Detection.scan_page_id)
        .join(Exercise, Exercise.id == Detection.exercise_id)
        .where(ScanPage.scan_id == scan_id)
        .where(ScanPage.discarded.is_(False))
        .where(ScanPage.wrong_class.is_(False))
        .where(Detection.outcome == DetectionOutcome.PENDING)
        .order_by(ScanPage.page_index.asc(), Detection.item_index.asc())
    ).all()
    return [(detection, exercise) for detection, exercise in rows]


def _fill_for(db: Session, detection: Detection) -> str:
    """Which guides the crop carried, told to the model so it ignores them."""
    row = db.execute(
        select(AnswerBoxPlacement.box_fill)
        .join(ScanPage, ScanPage.id == detection.scan_page_id)
        .join(Scan, Scan.id == ScanPage.scan_id)
        .where(AnswerBoxPlacement.sheet_id == Scan.sheet_id)
        .where(AnswerBoxPlacement.student_uid == ScanPage.detected_uid)
        .where(AnswerBoxPlacement.item_index == detection.item_index)
    ).scalars().first()
    return _FILL_WORDS.get(row.value if row is not None else "lined", _FILL_WORDS["lined"])


def _settle(
    detection: Detection,
    *,
    outcome: DetectionOutcome,
    confidence: float,
    transcription: str | None = None,
    verdict: bool | None = None,
    model: str | None = None,
) -> None:
    """Write the machine's reading, once, into both halves of the row."""
    detection.transcription = detection.machine_transcription = transcription
    detection.verdict_correct = detection.machine_verdict_correct = verdict
    detection.outcome = detection.machine_outcome = outcome
    detection.confidence = detection.machine_confidence = confidence
    detection.vision_model = model


def _ungradeable(detection: Detection, *, transcription: str | None = None) -> None:
    _settle(
        detection,
        outcome=DetectionOutcome.NOT_GRADEABLE,
        confidence=0.0,
        transcription=transcription,
    )


def grade_one(
    db: Session,
    storage: Storage,
    ai: AiClient,
    *,
    detection: Detection,
    exercise: Exercise,
) -> DetectionOutcome:
    """One box, one call, one settled row. Never raises."""
    if not ai.chat_is_grounded or not detection.crop_key:
        _ungradeable(detection)
        return DetectionOutcome.NOT_GRADEABLE
    try:
        image = storage.get_bytes(detection.crop_key)
        response, record = ai.complete(
            prompt=load_prompt(PROMPT_NAME, PROMPT_VERSION),
            purpose=PROMPT_NAME,
            values={
                "language": exercise.language,
                "statement": exercise.statement,
                "expected_answer": exercise.answer_text or "(no expected answer was recorded)",
                "fill": _fill_for(db, detection),
            },
            images=(ImagePart(image),),
            temperature=0.0,
        )
        record_calls(db, school_id=detection.school_id, records=[record])
        data = parse_json_response(response.text)
    except Exception as exc:
        log.warning(
            "open_grading.call_failed",
            detection_id=str(detection.id),
            error=type(exc).__name__,
        )
        _ungradeable(detection)
        return DetectionOutcome.NOT_GRADEABLE

    transcription = data.get("transcription")
    transcription = str(transcription).strip() if transcription else None
    written = data.get("written")
    correct = data.get("correct")
    try:
        confidence = float(max(0.0, min(1.0, float(data.get("confidence") or 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    if written is False:
        _settle(
            detection,
            outcome=DetectionOutcome.BLANK,
            confidence=confidence,
            transcription=transcription,
            model=response.model,
        )
        return DetectionOutcome.BLANK
    if not isinstance(correct, bool):
        _settle(
            detection,
            outcome=DetectionOutcome.NOT_GRADEABLE,
            confidence=confidence,
            transcription=transcription,
            model=response.model,
        )
        return DetectionOutcome.NOT_GRADEABLE

    outcome = (
        DetectionOutcome.DETECTED if confidence >= LOW_CONFIDENCE else DetectionOutcome.LOW_CONFIDENCE
    )
    _settle(
        detection,
        outcome=outcome,
        confidence=confidence,
        transcription=transcription,
        verdict=correct,
        model=response.model,
    )
    return outcome


def grade_open_answers(
    db: Session,
    storage: Storage,
    ai: AiClient,
    *,
    scan_id: uuid.UUID,
    on_progress: ProgressCB | None = None,
) -> dict[str, Any]:
    """Grade every pending written answer of one scan. The job's entry point."""
    pending = pending_detections(db, scan_id)
    counts: dict[str, int] = {"graded": 0, "blank": 0, "ungradeable": 0}
    total = len(pending)
    for index, (detection, exercise) in enumerate(pending):
        outcome = grade_one(db, storage, ai, detection=detection, exercise=exercise)
        if outcome is DetectionOutcome.BLANK:
            counts["blank"] += 1
        elif outcome is DetectionOutcome.NOT_GRADEABLE:
            counts["ungradeable"] += 1
        else:
            counts["graded"] += 1
        # Committed as it lands: a crash on answer 40 keeps the first 39.
        db.commit()
        if on_progress is not None:
            on_progress((index + 1) / max(1, total), f"answer {index + 1} of {total}")

    # Rule 1. Anything the loop above did not reach — it cannot happen inside
    # it, but a row can be left behind by a page assigned by hand while this
    # job ran — is settled here rather than left as a promise.
    for detection, _ in pending_detections(db, scan_id):
        _ungradeable(detection)
        counts["ungradeable"] += 1
    db.commit()

    log.info("open_grading.done", scan_id=str(scan_id), **counts)
    return {"pending": total, **counts}


def chain_open_grading(db: Session, job: Job) -> Job | None:
    """The follow-up job for a finished ``PROCESS_SCAN``, or ``None`` when
    nothing is pending. Writes the row; the caller enqueues it.

    Chained rather than inlined so the scan job stays a pure OpenCV pass that
    flips the pile to review the moment the marks are read; a model call per
    written answer would hold that screen closed for a whole class set."""
    if job.kind is not JobKind.PROCESS_SCAN or job.status is not JobStatus.SUCCEEDED:
        return None
    pending = int((job.result or {}).get("pending_open_answers") or 0)
    if pending <= 0:
        return None
    scan_id = (job.payload or {}).get("scan_id")
    if not scan_id:
        return None
    follow_up = Job(
        id=uuid.uuid4(),
        school_id=job.school_id,
        kind=JobKind.GRADE_OPEN_ANSWERS,
        status=JobStatus.QUEUED,
        progress=0.0,
        message="reading the written answers",
        payload={"scan_id": str(scan_id), "after_job_id": str(job.id)},
    )
    db.add(follow_up)
    db.flush()
    return follow_up


__all__ = ["chain_open_grading", "grade_one", "grade_open_answers", "pending_detections"]
