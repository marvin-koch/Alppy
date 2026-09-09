"""The curriculum tree: Class -> Branch -> Competence -> Theme, with mastery.

A separate module from ``mastery_service`` on purpose. That one's docstring
promises "attempts in, bands out" and it keeps that promise; this one walks
curriculum STRUCTURE — ``class_subject``, ``Chapter.primary_competency_id``,
``Competency.parent_id`` — and leans on mastery for the arithmetic. The same
split that already separates ``class_service`` from ``sheet_service``.

Two invariants worth stating up front, because both are easy to break by
accident later:

**The `unfiled` bucket is excluded by ``primary_competency_id IS NULL``, never
by its ``key``.** A school may relabel it; a rename must not readmit sheets
nobody has filed into a mastery number.

**Nothing here reads ``Attempt.score``.** Every input is a ``MasteryResult``,
and those are built only from ``Attempt.correct`` (see
``mastery_service.load_attempt_inputs``), so the barème cannot reach the model
through this path even by mistake. A marking scheme must not be able to rewrite
what the model believes a child knows.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.api.deps import Scope
from alppy.mastery.model import MasteryResult, compute_mastery, roll_up_mastery
from alppy.models import (
    UNFILED_CHAPTER_KEY,
    Chapter,
    Competency,
    Exercise,
    Sheet,
    Subject,
)
from alppy.schemas import (
    ClassTreeOut,
    TreeBranchOut,
    TreeCompetenceOut,
    TreeThemeOut,
)
from alppy.services import class_service, mastery_service
from alppy.services.mastery_service import mastery_out


# Worst first, so `min` over this order finds the weakest assessed child.
def class_tree(
    db: Session,
    scope: Scope,
    class_id: uuid.UUID,
    *,
    subject_id: uuid.UUID | None = None,
    student_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ClassTreeOut:
    """The navigation tree for one class, every node carrying a band.

    Pooled across the whole roster by default; ``student_id`` narrows it to one
    child's own attempts, which is the same computation over a shorter list.
    ``subject_id`` narrows to one Branch, for a caller that already knows which
    subject it is composing in.
    """
    at = now or datetime.now(UTC)
    school_class = class_service.get_class(db, scope, class_id)

    if student_id is not None:
        student_ids = [mastery_service._owned_student(db, scope, student_id).id]
    else:
        student_ids = [s.id for s in class_service.list_students(db, scope, school_class.id)]

    branch_ids = class_service.subject_ids_for_class(db, scope, school_class.id)
    if subject_id is not None:
        branch_ids = [b for b in branch_ids if b == subject_id]
    if not branch_ids:
        return ClassTreeOut(class_id=school_class.id, branches=[], computed_at=at)

    subjects = {
        row.id: row
        for row in db.scalars(
            select(Subject)
            .where(Subject.id.in_(branch_ids))
            .where(Subject.school_id == scope.school_id)
        )
    }

    branches: list[TreeBranchOut] = []
    for branch_id in branch_ids:  # keep class_subject.position order
        subject = subjects.get(branch_id)
        if subject is None:  # pragma: no cover - a declared subject always exists
            continue
        branches.append(
            _branch(db, scope, school_class.id, subject, student_ids=student_ids, now=at)
        )

    return ClassTreeOut(class_id=school_class.id, branches=branches, computed_at=at)


def _branch(
    db: Session,
    scope: Scope,
    class_id: uuid.UUID,
    subject: Subject,
    *,
    student_ids: list[uuid.UUID],
    now: datetime,
) -> TreeBranchOut:
    chapters = list(
        db.scalars(
            select(Chapter)
            .where(Chapter.school_id == scope.school_id)
            .where(Chapter.subject_id == subject.id)
            .where(Chapter.primary_competency_id.is_not(None))
            .order_by(Chapter.position.asc())
        )
    )

    unfiled_sheets = (
        db.execute(
            select(func.count(Sheet.id))
            .join(Chapter, Chapter.id == Sheet.chapter_id)
            .where(Sheet.class_id == class_id)
            .where(Sheet.school_id == scope.school_id)
            .where(Chapter.subject_id == subject.id)
            .where(Chapter.key == UNFILED_CHAPTER_KEY)
        ).scalar_one()
        or 0
    )

    untagged_exercises = (
        db.execute(
            select(func.count(Exercise.id))
            .where(Exercise.school_id == scope.school_id)
            .where(Exercise.subject_id == subject.id)
            .where(Exercise.chapter_id.is_(None))
            .where(Exercise.discarded_at.is_(None))
        ).scalar_one()
        or 0
    )

    if not chapters:
        empty = roll_up_mastery([])
        return TreeBranchOut(
            subject_id=subject.id,
            subject_key=subject.key,
            labels=dict(subject.labels or {}),
            mastery=mastery_out(empty, []),
            competences=[],
            unfiled_sheet_count=int(unfiled_sheets),
            unfiled_exercise_count=int(untagged_exercises),
        )

    # One query for every attempt this branch's chapters can credit, then an
    # in-memory fold — no N+1 across chapters.
    needed: set[uuid.UUID] = set()
    for chapter in chapters:
        needed.update(c.id for c in chapter.competencies)

    pooled = mastery_service.pool_by_competency(
        mastery_service.load_attempt_inputs(
            db,
            scope.school_id,
            student_ids,
            subject_id=subject.id,
            competency_ids=sorted(needed),
            as_of=now,
        )
    )

    sheet_counts: dict[uuid.UUID, int] = {
        chapter_id: int(count)
        for chapter_id, count in db.execute(
            select(Sheet.chapter_id, func.count(Sheet.id))
            .where(Sheet.class_id == class_id)
            .where(Sheet.school_id == scope.school_id)
            .group_by(Sheet.chapter_id)
        ).all()
    }

    # Group Themes under their Competence: the PARENT of the chapter's primary,
    # or the primary itself when it is already top-level. Without that fallback
    # a top-level primary would produce a nameless Competence with one Theme.
    themes_by_competence: dict[uuid.UUID, list[tuple[Chapter, MasteryResult, list[MasteryResult]]]]
    themes_by_competence = defaultdict(list)
    competence_order: list[uuid.UUID] = []

    for chapter in chapters:
        primary = chapter.primary_competency
        if primary is None:  # pragma: no cover - filtered by the query above
            continue
        children = [compute_mastery(pooled.get(c.id, []), now) for c in chapter.competencies]
        theme_mastery = roll_up_mastery(children)
        competence_id = primary.parent_id or primary.id
        if competence_id not in themes_by_competence:
            competence_order.append(competence_id)
        themes_by_competence[competence_id].append((chapter, theme_mastery, children))

    competencies = {
        row.id: row
        for row in db.scalars(select(Competency).where(Competency.id.in_(competence_order)))
    }

    competences: list[TreeCompetenceOut] = []
    # Kept alongside the serialised nodes: the Branch rolls up from these
    # RESULTS, never from the percentages already rendered onto them —
    # averaging displayed numbers would lose the evidence weighting.
    competence_results: list[MasteryResult] = []

    for competence_id in competence_order:
        node = competencies.get(competence_id)
        if node is None:  # pragma: no cover - the FK guarantees it
            continue
        entries = themes_by_competence[competence_id]
        theme_results = [m for _chapter, m, _children in entries]
        rolled_competence = roll_up_mastery(theme_results)
        competence_results.append(rolled_competence)
        competences.append(
            TreeCompetenceOut(
                competency_id=node.id,
                code=node.code,
                labels=dict(node.labels or {}),
                mastery=mastery_out(rolled_competence, theme_results),
                themes=[
                    TreeThemeOut(
                        chapter_id=chapter.id,
                        key=chapter.key,
                        labels=dict(chapter.labels or {}),
                        position=chapter.position,
                        sheet_count=sheet_counts.get(chapter.id, 0),
                        competency_ids=[c.id for c in chapter.competencies],
                        mastery=mastery_out(mastery, children),
                    )
                    for chapter, mastery, children in entries
                ],
            )
        )

    rolled = roll_up_mastery(competence_results)

    return TreeBranchOut(
        subject_id=subject.id,
        subject_key=subject.key,
        labels=dict(subject.labels or {}),
        mastery=mastery_out(rolled, competence_results),
        competences=competences,
        unfiled_sheet_count=int(unfiled_sheets),
        unfiled_exercise_count=int(untagged_exercises),
    )
