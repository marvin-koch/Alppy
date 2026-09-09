"""Who sits in a class, and which classes a teacher owns.

Its own module for one reason: ``class_service`` imports ``mastery_service``
(for ``band_summary``), so ``mastery_service`` cannot import it back. These
three subqueries are needed on both sides of that edge, and every scoped read
in the API funnels through one of them — a laxer rule invented in a new read
path is how a roster leaks (I-platform-03).

Nothing here touches the session: they are ``Select`` objects a caller drops
into an ``IN``, which is what lets one definition serve a count, a join and a
filter without three versions drifting apart.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from alppy.api.deps import Scope
from alppy.models import Class, class_student


def owned_class_ids(scope: Scope) -> Select[tuple[uuid.UUID]]:
    """The ids of the classes this teacher owns, as a subquery.

    Everything that hangs off a class — roster, mastery, sheets, scans —
    filters through this rather than through ``school_id`` alone (D23).
    """
    return (
        select(Class.id)
        .where(Class.school_id == scope.school_id)
        .where(Class.teacher_id == scope.teacher_id)
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
    """Every student sitting in any class this teacher owns.

    The student half of ``owned_class_ids``. Enrollment widens WHO a teacher
    may read, never which school: every caller keeps its own
    ``Student.school_id`` filter on top (I-platform-10).
    """
    return select(class_student.c.student_id).where(
        class_student.c.class_id.in_(owned_class_ids(scope))
    )
