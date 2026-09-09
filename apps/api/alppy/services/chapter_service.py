"""The per-subject `unfiled` Theme, and the one place it is created.

``Sheet.chapter_id`` is NOT NULL, so every subject needs a chapter to fall back
on before a teacher can create a sheet in it at all. That row is infrastructure,
not curriculum content: it carries no ``primary_competency_id``, it is excluded
from the navigation tree and from every roll-up, and its labels are fixed.

It is created eagerly by migration 0016 and by the reference seed, and lazily
here. The laziness is deliberate: a subject that reached the database by any
other route would otherwise make ``POST /sheets`` fail with a 422 the teacher
can neither understand nor fix. A missing structural row is ours to repair, not
theirs to report.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from alppy.models import UNFILED_CHAPTER_KEY, Chapter

UNFILED_POSITION = 999
"""Past every seeded chapter's 0..6, so a plain ``ORDER BY position`` puts the
bucket last without a second query to filter it out."""

UNFILED_LABELS: dict[str, str] = {
    "fr": "Non classé",
    "de": "Nicht zugeordnet",
    "en": "Unfiled",
}


def ensure_unfiled_chapter(
    db: Session, *, school_id: uuid.UUID, subject_id: uuid.UUID
) -> Chapter:
    """The subject's `unfiled` chapter, creating it if it is missing.

    Idempotent by ``(school_id, subject_id, key)``. Flushes, so the caller can
    use the id straight away.
    """
    # Insert-then-read rather than read-then-insert: the first sheet ever
    # created in a subject is exactly when this row does not exist yet, and two
    # of those at once would otherwise both see nothing and both insert,
    # splitting the subject's unfiled sheets across two buckets. `uq_chapter_key`
    # makes the ON CONFLICT meaningful.
    db.execute(
        pg_insert(Chapter)
        .values(
            id=uuid.uuid4(),
            school_id=school_id,
            subject_id=subject_id,
            key=UNFILED_CHAPTER_KEY,
            labels=dict(UNFILED_LABELS),
            position=UNFILED_POSITION,
            # Never a parent, never in the tree, never in a roll-up.
            primary_competency_id=None,
        )
        .on_conflict_do_nothing(constraint="uq_chapter_key")
    )
    row = db.execute(
        select(Chapter)
        .where(Chapter.school_id == school_id)
        .where(Chapter.subject_id == subject_id)
        .where(Chapter.key == UNFILED_CHAPTER_KEY)
    ).scalar_one()
    row.labels = dict(UNFILED_LABELS)
    row.position = UNFILED_POSITION
    row.primary_competency_id = None
    db.flush()
    return row


def ensure_unfiled_chapters(
    db: Session, *, school_id: uuid.UUID, subject_ids: dict[str, uuid.UUID]
) -> dict[str, uuid.UUID]:
    """One per subject, keyed by subject key. Used by the reference seed."""
    return {
        subject_key: ensure_unfiled_chapter(
            db, school_id=school_id, subject_id=subject_id
        ).id
        for subject_key, subject_id in subject_ids.items()
    }
