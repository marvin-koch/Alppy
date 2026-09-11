"""The two numbers that would show grading quality degrading in the field.

There is no error tracker, no metrics backend and no alerting (D8). These two
signals need none of that, because both are already sitting in Postgres and
have been since the scan pipeline was written:

* **The override rate.** `Detection` keeps what the MACHINE read in
  `machine_index` / `machine_outcome` / `machine_verdict_correct`, written once
  and never updated, beside the value the teacher may have replaced. So "how
  often does a teacher disagree with the scanner" is a comparison between two
  columns of one row, and nobody has ever run it.
* **The confidence distribution.** `machine_confidence` is on every row.

Why these and not uptime: the failure mode that matters here is not the API
going down — that is loud. It is a specific school's printer, photocopier or
classroom lighting drifting away from what the detector was tuned against, so
that readings quietly get worse for that school and nobody else. Today the only
signal is a teacher eventually saying "it's about 90% right", which never
reaches anybody as a number.

**Disagreement is not the same as review**, and getting that wrong would make
this meaningless. `correct_detection` stamps `CORRECTED` whatever value it is
sent, because a teacher who opens a low-confidence row and agrees affirms by
re-sending the same reading (T24). So counting `outcome == CORRECTED` counts
*attention*, not error. What this measures is the stored value differing from
the machine's — and it reports the review count too, because an override rate
over a pile nobody opened is a different number from one over a pile that was
read line by line.

**No student data.** Every row here is a count, grouped by school. Nothing
identifies a pupil, a teacher or a page, which is what lets these be logged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, Integer, and_, case, cast, func, or_, select
from sqlalchemy.orm import Session

from alppy.core.logging import get_logger
from alppy.models import Detection, ScanPage, School

log = get_logger(__name__)

#: How far back a weekly run looks.
DEFAULT_WINDOW_DAYS = 7

#: Ten buckets over [0, 1]. A confidence of exactly 1.0 would land in an
#: eleventh; it belongs in the top one.
DECILES = 10


@dataclass(frozen=True, slots=True)
class OverrideRate:
    """One school's week."""

    school_id: uuid.UUID
    school_name: str
    machine_readings: int
    """Detections the machine actually read — the denominator. A row with no
    `machine_outcome` was never a machine reading (a pending written answer, a
    row created by a teacher) and must not dilute the rate."""
    reviewed: int
    """Rows a teacher opened and answered on, agreement included."""
    overridden: int
    """Rows where the stored value DIFFERS from the machine's."""

    @property
    def override_rate(self) -> float:
        """Overridden over every machine reading. The headline number."""
        return self.overridden / self.machine_readings if self.machine_readings else 0.0

    @property
    def disagreement_when_reviewed(self) -> float:
        """Overridden over the rows a teacher actually looked at.

        The two together are the honest picture: a low override rate over a
        pile nobody opened says nothing about the scanner."""
        return self.overridden / self.reviewed if self.reviewed else 0.0


@dataclass(frozen=True, slots=True)
class ConfidenceDistribution:
    school_id: uuid.UUID
    school_name: str
    #: Counts per decile, index 0 = [0.0, 0.1) … index 9 = [0.9, 1.0].
    buckets: tuple[int, ...]

    @property
    def total(self) -> int:
        return sum(self.buckets)

    @property
    def below_half(self) -> int:
        """How much of the week the detector was closer to guessing than reading."""
        return sum(self.buckets[:5])


@dataclass(frozen=True, slots=True)
class RegistrationRate:
    """Pages whose four fiducials could not be located.

    The most diagnostic single number in the pipeline for "something about the
    physical inputs has changed" — a new photocopier, a different paper, a
    darker classroom. A page that does not register produces no readings at
    all, so it never appears in the override rate."""

    school_id: uuid.UUID
    school_name: str
    pages: int
    failed: int

    @property
    def failure_rate(self) -> float:
        return self.failed / self.pages if self.pages else 0.0


def _window(days: int) -> tuple[datetime, datetime]:
    until = datetime.now(UTC)
    return until - timedelta(days=days), until


def _machine_disagreed() -> ColumnElement[bool]:
    """The predicate for "the stored value is not what the machine read".

    Three readings on one row and any of them can be overridden independently:
    the bubble index, the written answer's verdict, and the transcription. A
    teacher who fixes a misread word without changing the verdict has still
    corrected the machine.

    `is_distinct_from` rather than `!=` throughout, because NULL is a real
    value here — "the machine read nothing and the teacher wrote something" is
    an override, and `!=` would answer NULL and drop the row.
    """
    return or_(
        and_(
            Detection.machine_index.is_not(None),
            Detection.detected_index.is_distinct_from(Detection.machine_index),
        ),
        and_(
            Detection.machine_verdict_correct.is_not(None),
            Detection.verdict_correct.is_distinct_from(Detection.machine_verdict_correct),
        ),
        and_(
            Detection.machine_transcription.is_not(None),
            Detection.transcription.is_distinct_from(Detection.machine_transcription),
        ),
    )


def override_rates(db: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> list[OverrideRate]:
    """One row per school that graded anything in the window.

    Runs as the OWNER (the CLI's `admin_session`), because it is deliberately
    cross-school: the question is which school is drifting, and a query bound
    to one tenant cannot answer it. Nothing it returns identifies a person.
    """
    since, _ = _window(days)
    rows = db.execute(
        select(
            School.id,
            School.name,
            func.count().label("machine_readings"),
            func.sum(case((Detection.corrected_at.is_not(None), 1), else_=0)).label("reviewed"),
            func.sum(case((_machine_disagreed(), 1), else_=0)).label("overridden"),
        )
        .select_from(Detection)
        .join(School, School.id == Detection.school_id)
        .where(Detection.machine_outcome.is_not(None))
        .where(Detection.created_at >= since)
        .group_by(School.id, School.name)
        .order_by(School.name)
    ).all()
    return [
        OverrideRate(
            school_id=row[0],
            school_name=row[1],
            machine_readings=int(row[2] or 0),
            reviewed=int(row[3] or 0),
            overridden=int(row[4] or 0),
        )
        for row in rows
    ]


def confidence_distributions(
    db: Session, *, days: int = DEFAULT_WINDOW_DAYS
) -> list[ConfidenceDistribution]:
    """The `machine_confidence` histogram, per school.

    Bucketed in SQL and clamped in Python: `cast(c * 10 as int)` puts a
    confidence of exactly 1.0 in an eleventh bucket, and `LEAST`/`MIN` are
    spelled differently on Postgres and SQLite — so the fold happens where it
    costs nothing and reads the same on both.
    """
    since, _ = _window(days)
    bucket = cast(Detection.machine_confidence * DECILES, Integer).label("bucket")
    rows = db.execute(
        select(School.id, School.name, bucket, func.count())
        .select_from(Detection)
        .join(School, School.id == Detection.school_id)
        .where(Detection.machine_confidence.is_not(None))
        .where(Detection.created_at >= since)
        .group_by(School.id, School.name, bucket)
    ).all()

    per_school: dict[uuid.UUID, list[int]] = {}
    names: dict[uuid.UUID, str] = {}
    for school_id, name, raw_bucket, count in rows:
        buckets = per_school.setdefault(school_id, [0] * DECILES)
        names[school_id] = name
        index = min(DECILES - 1, max(0, int(raw_bucket or 0)))
        buckets[index] += int(count)
    return [
        ConfidenceDistribution(
            school_id=school_id, school_name=names[school_id], buckets=tuple(buckets)
        )
        for school_id, buckets in sorted(per_school.items(), key=lambda kv: names[kv[0]])
    ]


def registration_rates(db: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> list[RegistrationRate]:
    since, _ = _window(days)
    rows = db.execute(
        select(
            School.id,
            School.name,
            func.count().label("pages"),
            func.sum(case((ScanPage.registered.is_(False), 1), else_=0)).label("failed"),
        )
        .select_from(ScanPage)
        .join(School, School.id == ScanPage.school_id)
        .where(ScanPage.created_at >= since)
        .group_by(School.id, School.name)
        .order_by(School.name)
    ).all()
    return [
        RegistrationRate(
            school_id=row[0],
            school_name=row[1],
            pages=int(row[2] or 0),
            failed=int(row[3] or 0),
        )
        for row in rows
    ]


def report(db: Session, *, days: int = DEFAULT_WINDOW_DAYS) -> int:
    """Compute all three and log them. Returns the number of schools seen.

    Logged rather than written to a summary table, for now. A table is the
    better answer — a trend needs history, and a log line is only useful while
    somebody is reading logs — but it is a migration and a schema-drift check,
    and the thing that is actually missing today is the *number*, not its
    archive. `structlog` renders these as JSON in a deployment, so an
    aggregator can pick them up the day one exists.
    """
    seen: set[uuid.UUID] = set()

    for rate in override_rates(db, days=days):
        seen.add(rate.school_id)
        log.info(
            "health_signal.override_rate",
            school=rate.school_name,
            school_id=str(rate.school_id),
            window_days=days,
            machine_readings=rate.machine_readings,
            reviewed=rate.reviewed,
            overridden=rate.overridden,
            override_rate=round(rate.override_rate, 4),
            disagreement_when_reviewed=round(rate.disagreement_when_reviewed, 4),
        )

    for dist in confidence_distributions(db, days=days):
        seen.add(dist.school_id)
        log.info(
            "health_signal.confidence",
            school=dist.school_name,
            school_id=str(dist.school_id),
            window_days=days,
            total=dist.total,
            deciles=list(dist.buckets),
            below_half=dist.below_half,
        )

    for reg in registration_rates(db, days=days):
        seen.add(reg.school_id)
        # Warning rather than info past a threshold: a page that does not
        # register produces no readings at all, so a school whose photocopier
        # has drifted disappears from the override rate rather than showing up
        # in it. One in twenty is already a teacher re-photographing pages.
        emit = log.warning if reg.failure_rate > 0.05 else log.info
        emit(
            "health_signal.registration",
            school=reg.school_name,
            school_id=str(reg.school_id),
            window_days=days,
            pages=reg.pages,
            failed=reg.failed,
            failure_rate=round(reg.failure_rate, 4),
        )

    log.info("health_signal.done", schools=len(seen), window_days=days)
    return len(seen)
