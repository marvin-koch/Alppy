"""Who sits in a class, and what a teacher may read about it.

Its own module for one reason: ``class_service`` imports ``mastery_service``
(for ``band_summary``), so ``mastery_service`` cannot import it back. These
subqueries are needed on both sides of that edge, and every scoped read in the
API funnels through one of them — a laxer rule invented in a new read path is
how a roster leaks (I-platform-03).

Since D73 there are **two grains**, and the names carry which is which so a
reviewer can tell at a glance what a new read path used:

    owned_*   CLASS-GRAINED   may I know this class and these children exist?
    taught_*  PAIR-GRAINED    may I see this teaching artefact and this evidence?

**Who you may name is class-grained; what you may see about them is
pair-grained.** A maître de classe who teaches nothing still runs the roster; a
co-teacher who takes French sees the child and the French evidence and nothing
else. Both failure modes are real and they are mirror images: a laxer rule
leaks a colleague's branch into your matrix, and a *stricter* rule invented in
a new read path locks a co-teacher out of the class they teach.

Nothing here touches the session: they are ``Select`` objects (or, for
``taught_here``, a boolean expression) that a caller drops into an ``IN`` or a
``WHERE``, which is what lets one definition serve a count, a join and a filter
without three versions drifting apart.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.orm import QueryableAttribute

from alppy.api.deps import Scope
from alppy.models import Class, class_student, class_teacher_subject


def owned_class_ids(scope: Scope) -> Select[tuple[uuid.UUID]]:
    """The classes this teacher has any footing in — CLASS-GRAINED.

    Head teacher of, **or** holding any branch in. This gates a class's
    existence, its roster and its children's identities: everything that
    hangs off a class as a *group* filters through this rather than through
    ``school_id`` alone (D23, I-platform-11).

    It is **not** the gate for anything a teacher makes or marks — a sheet, a
    pile, a band. Those are ``taught_here``.

    The head-teacher arm is not decoration. It is what keeps a brand-new class
    with no declared branches visible to its own teacher, and it is what makes
    the 0021 backfill provably behaviour-preserving: afterwards every class's
    assignment set is exactly {head teacher} × {declared branches}, so this
    union selects the same classes the old single predicate did.
    """
    return (
        select(Class.id)
        .where(Class.school_id == scope.school_id)
        .where(
            or_(
                Class.head_teacher_id == scope.teacher_id,
                Class.id.in_(
                    select(class_teacher_subject.c.class_id).where(
                        class_teacher_subject.c.teacher_id == scope.teacher_id
                    )
                ),
            )
        )
    )


# A column as either half of `taught_here` may arrive as a mapped attribute
# (`Sheet.class_id`) or as a plain expression, and SQLAlchemy's stubs do not
# make the first a subtype of the second. Spelling the union once beats a
# `type: ignore` at all six call sites.
ColumnExpr = ColumnElement[Any] | QueryableAttribute[Any]


def taught_here(
    class_col: ColumnExpr,
    subject_col: ColumnExpr,
    scope: Scope,
) -> ColumnElement[bool]:
    """Does this teacher take THIS branch in THIS class — PAIR-GRAINED.

    Takes the two columns rather than a row id because the rows that need it
    already carry both: ``Sheet``, and ``Event`` via ``subject_area_id``.

    A correlated ``EXISTS`` rather than ``tuple_(a, b).in_(...)``: row-value
    ``IN`` is fine on Postgres, but the suite runs on SQLite (D18) and the
    tenancy predicate is not the place to discover a dialect difference.

    ``ColumnElement[Any]`` because two of the callers pass **nullable**
    columns (``Event.class_id``, ``Event.subject_area_id``). That is not a
    weakening: a NULL on either side simply matches no assignment row, which
    is the right answer — a staffroom event belongs to no class, and a
    class-level one to no branch, so neither is "taught" by anybody. The
    caller decides what those rows deserve; see ``api/v1/timeline.py``.
    """
    return (
        select(class_teacher_subject.c.class_id)
        .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
        .where(class_teacher_subject.c.class_id == class_col)
        .where(class_teacher_subject.c.subject_id == subject_col)
        .exists()
    )


def taught_subject_ids(scope: Scope, class_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """The branches this teacher takes in ONE class, as a subquery.

    May legitimately be empty — a head teacher who teaches nothing gets a
    roster and an empty tree, which is the right answer and not a 404.
    """
    return select(class_teacher_subject.c.subject_id).where(
        and_(
            class_teacher_subject.c.teacher_id == scope.teacher_id,
            class_teacher_subject.c.class_id == class_id,
        )
    )


def taught_subject_ids_anywhere(scope: Scope) -> Select[tuple[uuid.UUID]]:
    """Every branch this teacher takes, in any class of this school.

    The corpus is deliberately staffroom-shared (I-platform-04), so this is a
    narrowing for *writes* that reach into it, never a gate on reads.
    """
    return (
        select(class_teacher_subject.c.subject_id)
        .join(Class, Class.id == class_teacher_subject.c.class_id)
        .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
        .where(Class.school_id == scope.school_id)
        .distinct()
    )


def enrolled_student_ids(class_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """The ids of the students sitting in one class.

    "Sitting in", not "homed in": a student may be enrolled in several of one
    teacher's classes while only one of them minted their UID (D69). Every
    read a teacher browses — roster, matrix, tree, printed pile, adaptive
    targeting — means this one. ``Student.home_class_id`` means the other, and
    only the roster paste and the UID want it.
    """
    return select(class_student.c.student_id).where(class_student.c.class_id == class_id)


def enrolled_in_owned_classes(scope: Scope) -> Select[tuple[uuid.UUID]]:
    """Every student sitting in any class this teacher has a footing in.

    The student half of ``owned_class_ids``, and class-grained on purpose: a
    child is a child. Enrollment widens WHO a teacher may read, never which
    school — every caller keeps its own ``Student.school_id`` filter on top
    (I-platform-10). What that teacher may then *see* about the child is
    narrowed per branch by the caller, not here.
    """
    return select(class_student.c.student_id).where(
        class_student.c.class_id.in_(owned_class_ids(scope))
    )
