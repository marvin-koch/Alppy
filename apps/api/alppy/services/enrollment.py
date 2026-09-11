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

Since D87 there is a **third axis: when.** ``class_student`` and
``class_teacher_subject`` hold ended memberships as well as open ones, so every
subquery here takes ``on`` — the date to answer as of — and **it is a required
keyword argument with no default.** That is deliberate and it is the whole
safety mechanism of 0027: adding the columns without it would leave a dozen
read sites compiling unchanged while the tables underneath them started
returning history, and a roster silently gaining the pupils who left is a
worse bug than the one 0027 fixes. A required argument turns every one of
those sites into a type error the suite catches, which is what the renames in
0019 and 0021 bought by renaming.

The interval is half-open and lives in ``db/validity.py`` — below this module
and below ``api/deps``, because ``get_membership`` needs the same predicate and
this module already imports ``deps`` for ``Scope``.

Nothing here touches the session: they are ``Select`` objects (or, for
``taught_here``, a boolean expression) that a caller drops into an ``IN`` or a
``WHERE``, which is what lets one definition serve a count, a join and a filter
without three versions drifting apart.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.orm import QueryableAttribute

from alppy.api.deps import Scope
from alppy.db.validity import valid_on
from alppy.models import Class, class_student, class_teacher_subject


def owned_class_ids(scope: Scope, *, on: date) -> Select[tuple[uuid.UUID]]:
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

    The head-teacher arm is also **untimed**, and that is not an oversight:
    ``Class.head_teacher_id`` is a NOT NULL column on the class, not a
    membership, so a class is never unowned and there is no interval to ask
    about. Only the assignment arm takes ``on``.
    """
    return (
        select(Class.id)
        .where(Class.school_id == scope.school_id)
        .where(
            or_(
                Class.head_teacher_id == scope.teacher_id,
                Class.id.in_(
                    select(class_teacher_subject.c.class_id)
                    .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
                    .where(valid_on(class_teacher_subject, on))
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
    *,
    on: date,
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
        .where(valid_on(class_teacher_subject, on))
        .exists()
    )


def taught_here_ever(
    class_col: ColumnExpr,
    subject_col: ColumnExpr,
    scope: Scope,
) -> ColumnElement[bool]:
    """Did this teacher EVER take this branch in this class — PAIR-GRAINED.

    ``taught_here`` with the interval dropped, and the deliberate counterpart
    to it (D88). It is the gate for **reading a teaching artefact**, where
    ``taught_here`` stays the gate for touching one.

    The split exists because the two answers genuinely differ. M. Rossier takes
    niveau-2 maths from September to February and marks eleven sheets. In June
    a parent contests an orientation decision. Under a current-only gate he can
    open the pupil's profile — ``ever_shared_student_ids`` was widened for
    exactly that in 0027 — and then 404s on every sheet the profile links to,
    which is to say on all of the evidence. The widening was real but it
    stopped one join short of being usable: ``results_service.sheet_report``
    resolved the sheet through the current-only gate *before* reaching its own
    overlap-widened student lookup, so that lookup could not run in the one
    case its comment describes.

    **"Ever", not "overlap", and the asymmetry with ``ever_shared_student_ids``
    is the point.** A pupil is a person, so linking two people who never shared
    a room is a leak and the interval intersection is what prevents it. A sheet
    is not a person; it is the teaching material of a (class, branch), and a
    teacher who takes that pair over in March inheriting October's sheets is
    the correct answer rather than a tolerated one — they are teaching the same
    children the same branch.

    That is safe because it does not stand alone. Where a sheet-grained read
    names a child — ``sheet_report`` — the student is gated *separately* by
    ``ever_shared_student_ids``, and the two compose: Mme Dupont, arriving in
    March, opens the October sheet and reads the report only for the pupils
    whose time overlapped hers. Widening this predicate does not widen that
    one, and a caller that reaches a child through a sheet still owes its own
    student gate.

    Never use it for a write. Renders, edits, approvals and anything that bills
    a model call take ``taught_here(..., on=today())``: a teacher who has left
    the group may reconstruct what they marked, and may not print into it.
    """
    return (
        select(class_teacher_subject.c.class_id)
        .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
        .where(class_teacher_subject.c.class_id == class_col)
        .where(class_teacher_subject.c.subject_id == subject_col)
        .exists()
    )


def taught_subject_ids(scope: Scope, class_id: uuid.UUID, *, on: date) -> Select[tuple[uuid.UUID]]:
    """The branches this teacher takes in ONE class, as a subquery.

    May legitimately be empty — a head teacher who teaches nothing gets a
    roster and an empty tree, which is the right answer and not a 404.
    """
    return (
        select(class_teacher_subject.c.subject_id)
        .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
        .where(class_teacher_subject.c.class_id == class_id)
        .where(valid_on(class_teacher_subject, on))
    )


def taught_subject_ids_anywhere(scope: Scope, *, on: date) -> Select[tuple[uuid.UUID]]:
    """Every branch this teacher takes, in any class of this school.

    The corpus is deliberately staffroom-shared (I-platform-04), so this is a
    narrowing for *writes* that reach into it, never a gate on reads.
    """
    return (
        select(class_teacher_subject.c.subject_id)
        .join(Class, Class.id == class_teacher_subject.c.class_id)
        .where(class_teacher_subject.c.teacher_id == scope.teacher_id)
        .where(Class.school_id == scope.school_id)
        .where(valid_on(class_teacher_subject, on))
        .distinct()
    )


def enrolled_student_ids(class_id: uuid.UUID, *, on: date) -> Select[tuple[uuid.UUID]]:
    """The ids of the students sitting in one class.

    "Sitting in", not "homed in": a student may be enrolled in several of one
    teacher's classes while only one of them minted their UID (D69). Every
    read a teacher browses — roster, matrix, tree, printed pile, adaptive
    targeting — means this one. ``Student.home_class_id`` means the other, and
    only the roster paste and the UID want it.

    Pass a past ``on`` and this is the roster as it stood that day, which is
    what makes a matrix column honest about the group that actually sat the
    sheet.
    """
    return (
        select(class_student.c.student_id)
        .where(class_student.c.class_id == class_id)
        .where(valid_on(class_student, on))
    )


def enrolled_in_owned_classes(scope: Scope, *, on: date) -> Select[tuple[uuid.UUID]]:
    """Every student sitting in any class this teacher has a footing in.

    The student half of ``owned_class_ids``, and class-grained on purpose: a
    child is a child. Enrollment widens WHO a teacher may read, never which
    school — every caller keeps its own ``Student.school_id`` filter on top
    (I-platform-10). What that teacher may then *see* about the child is
    narrowed per branch by the caller, not here.
    """
    return (
        select(class_student.c.student_id)
        .where(class_student.c.class_id.in_(owned_class_ids(scope, on=on)))
        .where(valid_on(class_student, on))
    )


def ever_enrolled_student_ids(class_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """Everyone who has EVER sat in one class, open membership or ended.

    The one read that must not take an ``on``, and the reason it is spelled
    separately rather than as a default: it feeds the PII scrub list
    (``open_answer_grading``), where the set has to be a **superset** of the
    names that could appear on the paper. A pupil who left the group in
    February still wrote their name on the October copy sitting in the pile,
    and narrowing this to the current roster would quietly stop scrubbing it —
    a leak that no test fails on, because the gate only raises for names it
    was told about (docs/privacy.md).

    Never use it as a permission gate. It answers "whose name might be on this
    paper", not "whose record may this teacher read".
    """
    return select(class_student.c.student_id).where(class_student.c.class_id == class_id)


def ever_shared_student_ids(scope: Scope) -> Select[tuple[uuid.UUID]]:
    """Every student whose time in a class OVERLAPPED this teacher's time in it.

    The historical counterpart to ``enrolled_in_owned_classes``, and the
    reason 0027 was worth doing: M. Rossier taught Léa in the niveau-2 group
    from September to February and marked three of her sheets. When she moves
    to niveau 3 the current-enrolment gate 404s her profile, and he cannot
    reconstruct the group she was assessed in to justify her orientation to a
    parent.

    **Overlap, not "ever".** "Any pupil who was ever in a class I was ever in"
    would hand a teacher who joined in March a pupil who left in October —
    two people who never shared a room, linked by a group. The predicate is
    the ordinary interval intersection, with NULL read as "still open":

        pupil.valid_from < staff.valid_to  AND  staff.valid_from < pupil.valid_to

    The head-teacher arm has no interval — ``Class.head_teacher_id`` is a
    column on the class, so a maître de classe reaches every pupil the class
    ever held, which is what being accountable for a group means.

    This widens WHO a teacher may name, exactly as ``enrolled_in_owned_classes``
    does. It says nothing about what they may then see, which stays
    pair-grained and per branch at the caller.
    """
    staffing = class_teacher_subject
    overlap = and_(
        class_student.c.class_id == staffing.c.class_id,
        staffing.c.teacher_id == scope.teacher_id,
        or_(
            staffing.c.valid_to.is_(None),
            class_student.c.valid_from < staffing.c.valid_to,
        ),
        or_(
            class_student.c.valid_to.is_(None),
            staffing.c.valid_from < class_student.c.valid_to,
        ),
    )
    return (
        select(class_student.c.student_id)
        .join(Class, Class.id == class_student.c.class_id)
        .where(Class.school_id == scope.school_id)
        .where(
            or_(
                Class.head_teacher_id == scope.teacher_id,
                select(staffing.c.class_id).where(overlap).exists(),
            )
        )
        .distinct()
    )
