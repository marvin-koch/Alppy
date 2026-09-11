"""SQLAlchemy models for Alppy.

Tenancy: every domain table carries ``school_id`` — except ``School`` itself,
the curriculum (shared reference data, D11) and ``Teacher``, who may work at
more than one school and whose membership therefore lives in ``teacher_school``.
Every read path filters on the school resolved from the SESSION, never from a
teacher's row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    and_,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alppy.core.config import get_settings
from alppy.db.base import Base, SchoolScopedMixin, TimestampMixin
from alppy.models.enums import (
    AnswerBoxFill,
    ClassKind,
    CurriculumKind,
    DetectionOutcome,
    EventKind,
    EventSubject,
    ExerciseOrigin,
    ExerciseType,
    JobKind,
    JobStatus,
    Locale,
    MasteryBand,
    ScanStatus,
    SheetKind,
    SheetTarget,
)

_EMBED_DIM = get_settings().embedding_dim


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _fk(
    target: str, *, nullable: bool = False, ondelete: str = "CASCADE", index: bool = True
) -> Any:
    """A foreign key, indexed unless the caller says a composite already is.

    ``index=True`` is the default and stays it: an unindexed FK makes the
    referenced side's DELETE scan the whole child table, and finding that out
    in production is expensive. ``index=False`` is for the columns that LEAD a
    composite index declared on the same model — the btree prefix answers the
    same lookup, so the standalone index is written on every insert and read
    never (database audit M2). Every caller passing it names the covering
    index, so the claim is checkable without a database.
    """
    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
        index=index,
    )


# --------------------------------------------------------------------------
# Tenancy
# --------------------------------------------------------------------------
class School(Base, TimestampMixin):
    __tablename__ = "school"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    canton: Mapped[str | None] = mapped_column(String(2))
    default_curriculum: Mapped[CurriculumKind] = mapped_column(
        Enum(CurriculumKind, name="curriculum_kind"), default=CurriculumKind.PER
    )

    # The teachers BASED here. Not "the teachers who work here" — that is
    # `teacher_school`, and a teacher may appear in one school's staffroom
    # while being homed in another.
    home_teachers: Mapped[list[Teacher]] = relationship(back_populates="home_school")


teacher_school = Table(
    "teacher_school",
    Base.metadata,
    Column("teacher_id", PgUUID(as_uuid=True), ForeignKey("teacher.id", ondelete="CASCADE"), primary_key=True),
    Column("school_id", PgUUID(as_uuid=True), ForeignKey("school.id", ondelete="CASCADE"), primary_key=True),
    # When this teacher first joined. Provenance; `valid_from` is what the
    # reads use, and 0027 backfilled it from here.
    Column("joined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # The membership's own life. Leaving a school is `valid_to = today`, not a
    # deleted row — the block comment on `class_student` argues the trade once
    # for all three tables (D87). `valid_from` is in the PK so re-joining
    # after a gap is a second row rather than a conflict.
    Column(
        "valid_from",
        Date,
        primary_key=True,
        nullable=False,
        server_default=text("CURRENT_DATE"),
    ),
    Column("valid_to", Date, nullable=True),
    # "Who is in this staffroom" — the reverse of the composite PK's btree,
    # and the direction a colleague picker reads.
    Index("ix_teacher_school_school", "school_id", "teacher_id"),
    # At most one CURRENT membership per pair. The widened PK does not say
    # this: it would hold two open rows differing only in `valid_from`, which
    # is one teacher counted twice in a staffroom. This is also the index
    # `join_school` reopens against rather than conflicting on.
    Index(
        "uq_teacher_school_open",
        "teacher_id",
        "school_id",
        unique=True,
        postgresql_where=text("valid_to IS NULL"),
        sqlite_where=text("valid_to IS NULL"),
    ),
)


class Teacher(Base, TimestampMixin):
    """A teacher, who may work at more than one school.

    The ONLY table that is not ``SchoolScopedMixin`` besides ``School`` itself
    and the curriculum (D11) — and it is the second deliberate exception to
    I-platform-02, not an oversight. A row that carries one ``school_id`` is a
    row that belongs to one tenant; a teacher splitting their load between two
    establishments belongs to both, so the fact moved to ``teacher_school``
    and the column that stayed answers a different question (see below).

    Tenancy for a REQUEST therefore comes from the session, never from this
    row — ``deps.get_membership`` is the one place the cookie's school is
    checked against ``teacher_school`` (I-platform-14).
    """

    __tablename__ = "teacher"
    __table_args__ = (UniqueConstraint("email", name="uq_teacher_email"),)

    id: Mapped[uuid.UUID] = _pk()
    # WHERE THIS ACCOUNT IS BASED: the school it was created in, and the one
    # `login` mints the first cookie for. NOT "the school this request is
    # acting for" — that is `Scope.school_id`, and it comes from the session.
    #
    # Renamed from `school_id` rather than kept, on D69's reasoning: the old
    # name carried two facts that only looked like one while a teacher had a
    # single school, and under the old name every read site nobody reviewed
    # would have gone on compiling with the tenant meaning.
    home_school_id: Mapped[uuid.UUID] = _fk("school.id")
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # The display switches from DESIGN.md §8, persisted per teacher.
    # NULL means "not chosen" — which is a distinct state from light or dark.
    locale: Mapped[Locale] = mapped_column(
        Enum(Locale, name="locale"), default=Locale.FR, nullable=False
    )
    theme: Mapped[str | None] = mapped_column(String(10))  # None | light | dark
    contrast: Mapped[str | None] = mapped_column(String(10))  # None | high
    motion: Mapped[str | None] = mapped_column(String(10))  # None | off
    calm: Mapped[str | None] = mapped_column(String(10))  # None | on
    # Projector mode: names collapse to UIDs wherever pupils are listed.
    discreet: Mapped[str | None] = mapped_column(String(10))  # None | on

    home_school: Mapped[School] = relationship(back_populates="home_teachers")
    # Every school this teacher works at. viewonly: appending cannot re-issue
    # the session cookie, and a membership the cookie does not know about is a
    # membership no request can act on.
    # CURRENT memberships only. The table also holds ended ones since 0027,
    # and a relationship returning them would put a school a teacher has left
    # back into the switcher — the one read where "was a member" and "is a
    # member" must not be confused.
    schools: Mapped[list[School]] = relationship(
        secondary=teacher_school,
        primaryjoin=lambda: and_(
            Teacher.id == teacher_school.c.teacher_id,
            teacher_school.c.valid_to.is_(None),
        ),
        secondaryjoin=lambda: School.id == teacher_school.c.school_id,
        viewonly=True,
    )


class SchoolYear(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "school_year"
    __table_args__ = (
        # `2026/27`, the form every Swiss school writes on a timetable, pinned
        # in the database (audit 03, B24). The column was a free `String(20)`
        # and the label is not decoration: `current_school_year` looks a year up
        # BY LABEL when no row is marked current, so "2026/2027" and "2026/27"
        # would be two different years for one school — two rosters, two sets of
        # UIDs, and a class quietly created in the wrong one.
        #
        # `LIKE` with `_` wildcards rather than a regex: `~` is Postgres-only
        # and the suite builds its schema on SQLite (D18), where a check nobody
        # can run is a check nobody has.
        CheckConstraint("label LIKE '____/__'", name="ck_school_year_label"),
        # One row per label per school (0044). 0036 stopped the same year being
        # SPELLED two ways; this stops one spelling existing twice. Both are
        # needed, because `current_school_year` resolves a year BY LABEL when
        # no row is marked current, and `uq_student_uid` is keyed on the year:
        # two rows a human reads as one year are two rosters and two sets of
        # UIDs (audit H8).
        UniqueConstraint("school_id", "label", name="uq_school_year_label"),
        # A school has one current year, or none. Nothing enforced it, and the
        # read that depends on it papers over the ambiguity with `ORDER BY
        # starts_on DESC LIMIT 1` — so a second current row would not raise,
        # it would quietly make "the current year" mean whichever sorted first.
        Index(
            "uq_school_year_current",
            "school_id",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    label: Mapped[str] = mapped_column(String(20), nullable=False)  # "2025/26"
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Subject(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "subject"
    # Covered by `uq_subject_key (school_id, key)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    # Until subjects could only arrive from the seed this never mattered.
    # A create endpoint makes duplicates reachable, and `Competency.subject_key`
    # matches `Subject.key` BY STRING — two subjects keyed "mathematics" in one
    # school would split the curriculum silently, half the competencies
    # resolving to each. The constraint is the prerequisite, not a tidy-up.
    __table_args__ = (UniqueConstraint("school_id", "key", name="uq_subject_key"),)

    id: Mapped[uuid.UUID] = _pk()
    key: Mapped[str] = mapped_column(String(50), nullable=False)  # "mathematics"
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)


class_subject = Table(
    "class_subject",
    Base.metadata,
    Column("class_id", PgUUID(as_uuid=True), ForeignKey("class.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", PgUUID(as_uuid=True), ForeignKey("subject.id", ondelete="CASCADE"), primary_key=True),
    # "Which classes study this branch" — the reverse of the composite PK's
    # btree, and the direction a subject delete has to take (M1).
    Index("ix_class_subject_subject_id", "subject_id"),
    # Display order in the class's Branch nav: the order the class STARTED
    # studying each subject, not alphabetical. No column default — every write
    # path goes through ``class_service.declare_subject``, which computes the
    # next free position, the same convention ``SheetItem.position`` follows.
    Column("position", Integer, nullable=False),
)


class_teacher_subject = Table(
    "class_teacher_subject",
    Base.metadata,
    Column("class_id", PgUUID(as_uuid=True), primary_key=True),
    Column("teacher_id", PgUUID(as_uuid=True), ForeignKey("teacher.id", ondelete="RESTRICT"), primary_key=True),
    Column("subject_id", PgUUID(as_uuid=True), primary_key=True),
    # Provenance; `valid_from` is what the reads use and 0027 backfilled it
    # from here.
    Column("assigned_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Unassigning is `valid_to = today`. A remplaçant who covered March to May
    # becomes two dates on one row rather than a row that was there and then
    # was not — and the sheets they created (`Sheet.created_by_id`, SET NULL)
    # stop sitting in a class no record says they ever taught (D87).
    Column(
        "valid_from",
        Date,
        primary_key=True,
        nullable=False,
        server_default=text("CURRENT_DATE"),
    ),
    Column("valid_to", Date, nullable=True),
    # WHO TEACHES WHAT HERE. `class_subject` is the other half and they are
    # not interchangeable: that one is what the class STUDIES (a fact about
    # the class, carrying the Branch nav order), this one is who TEACHES it
    # (a fact about a teacher). Deriving the branch list from this table
    # instead would re-create the circularity D57 removed in a new costume —
    # a Branch would vanish from the navigation the moment its teacher was
    # unassigned, taking its Themes, its sheets and its bands with it.
    #
    # The composite FK is what makes "you cannot be assigned a branch this
    # class does not study" a constraint rather than a convention, and so
    # makes `class_subject` provably the superset the tree may trust. It is
    # only ENFORCED on Postgres — the test suite's SQLite does not turn on
    # `PRAGMA foreign_keys` — which is why `class_service.assign_branch`
    # declares the subject first rather than relying on it.
    ForeignKeyConstraint(
        ["class_id", "subject_id"],
        ["class_subject.class_id", "class_subject.subject_id"],
        name="fk_class_teacher_subject_class_subject",
        ondelete="CASCADE",
    ),
    # RESTRICT, not the module's usual CASCADE: ownership is assignment-based
    # now, so cascading here would let deleting an account strip a class of
    # its last owner — a roster of named children nobody can open, with no
    # error anywhere. `Class.head_teacher_id` is RESTRICT for the same reason.
    #
    # NOT school-scoped, like `class_subject` and `class_student`: every read
    # joins through a Class already filtered on the session's school. But
    # unlike those two this table has an end — the teacher — that CAN belong
    # to another school, so `assign_branch` asserts the membership the column
    # does not (I-platform-12).
    #
    # The composite PK's btree only answers class-first lookups. The reverse —
    # "which classes does this teacher hold a branch in" — is the TENANCY
    # query (`enrollment.owned_class_ids`), which runs on nearly every
    # request, so it gets its own index.
    Index("ix_class_teacher_subject_teacher", "teacher_id", "class_id"),
    # At most one CURRENT assignment per (class, teacher, branch) — see the
    # matching index on `class_student`.
    Index(
        "uq_class_teacher_subject_open",
        "class_id",
        "teacher_id",
        "subject_id",
        unique=True,
        postgresql_where=text("valid_to IS NULL"),
        sqlite_where=text("valid_to IS NULL"),
    ),
)


class_student = Table(
    "class_student",
    Base.metadata,
    Column("class_id", PgUUID(as_uuid=True), ForeignKey("class.id", ondelete="CASCADE"), primary_key=True),
    Column("student_id", PgUUID(as_uuid=True), ForeignKey("student.id", ondelete="CASCADE"), primary_key=True),
    # When this child first joined this class. Provenance; `valid_from` is
    # what the reads use, and 0027 backfilled it from here.
    Column("enrolled_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # THE MEMBERSHIP'S OWN LIFE, and the trade this table used to refuse.
    #
    # The old comment here was right about the cost — every roster read grows a
    # temporal predicate — and wrong about the balance. In Cycle 3 a pupil is
    # streamed into a maths niveau ACROSS homerooms and moves between them
    # mid-year, so "leaving is a deleted row" means the composition of a
    # teaching group is a snapshot that overwrites itself: Léa disappears from
    # the niveau-2 matrix including the October columns she sat, the teacher
    # who marked those sheets 404s on her profile, and nothing anywhere
    # records that she was ever in the group (D87).
    #
    # The predicate is paid for once, in `db/validity.py`, and `on` is a
    # REQUIRED keyword argument on every subquery in `services/enrollment.py`
    # precisely so no read path can keep the old meaning by accident.
    #
    # `valid_from` is in the PK: leaving in February and returning in May is
    # two rows, and the pair on its own is no longer unique.
    Column(
        "valid_from",
        Date,
        primary_key=True,
        nullable=False,
        server_default=text("CURRENT_DATE"),
    ),
    Column("valid_to", Date, nullable=True),
    # NOT school-scoped, like `class_subject` and `chapter_competency`: both
    # ends already are, and every read joins through a Class already filtered
    # on the session's school. Tenancy holds transitively (I-platform-02).
    #
    # The composite PK's btree only answers class-first lookups. The reverse
    # direction — "which classes is this student in" — is the TENANCY query
    # (`mastery_service._owned_student`), which runs on every student-profile
    # request, so it gets its own index.
    Index("ix_class_student_student_id", "student_id"),
    # At most one CURRENT enrollment per (class, pupil). The widened PK does
    # NOT say this — two open rows differing only in `valid_from` satisfy it,
    # and that is one child counted twice in every roster join and every
    # matrix column. This index is the guarantee, and it is what `enroll`
    # reopens against now that the key alone no longer collides.
    Index(
        "uq_class_student_open",
        "class_id",
        "student_id",
        unique=True,
        postgresql_where=text("valid_to IS NULL"),
        sqlite_where=text("valid_to IS NULL"),
    ),
)


class Class(Base, TimestampMixin, SchoolScopedMixin):
    """A teaching group. ``code`` is the Swiss short form, e.g. "7B"."""

    __tablename__ = "class"
    # Covered by `uq_class_code (school_id, school_year_id, code)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        UniqueConstraint("school_id", "school_year_id", "code", name="uq_class_code"),
    )

    id: Mapped[uuid.UUID] = _pk()
    school_year_id: Mapped[uuid.UUID] = _fk("school_year.id")
    # WHO THIS CLASS BELONGS TO: the maître de classe / Klassenlehrperson —
    # the one who pastes the roster, mints the UIDs and is accountable for the
    # group. Exactly one, NOT NULL, RESTRICT.
    #
    # It is NO LONGER the ownership axis. Who may read this class is
    # `enrollment.owned_class_ids`: the head teacher OR anyone holding a
    # `class_teacher_subject` row in it. Renamed from `teacher_id` on D69's
    # reasoning — under the old name every read site nobody reviewed would
    # have gone on compiling with "the owner" when it now means "the head
    # teacher", and `mastery_service._owned_student` is this change's
    # `scan_processing.wrong_class`.
    #
    # NOT NULL is load-bearing twice: it is what makes the 0021 backfill
    # provably behaviour-preserving for a class with no declared branches, and
    # it is why `unassign_branch` needs no "you cannot remove the last owner"
    # guard — a class can never become unowned.
    head_teacher_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="RESTRICT")
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    # Homeroom or course group. NULL is a third state and the default — "not
    # declared" — and NOT a synonym for HOMEROOM: every row predating 0026
    # predates the question, and answering it for them would invent a homeroom
    # out of the niveau groups the seed already contains.
    #
    # A discriminator, not a rule. Nothing branches on it yet: `class_student`
    # is many-to-many either way and `home_class_id` already carries which
    # class is a pupil's own. What it unlocks is a nav and a tree that can
    # stop weighting a support group the same as the group a child belongs to.
    kind: Mapped[ClassKind | None] = mapped_column(
        Enum(ClassKind, name="class_kind"), nullable=True
    )

    # The children this class is HOME to — the ones whose UID it minted. No
    # delete-orphan any more: with enrollment a student removed from this list
    # is not homeless, and deleting a class must never destroy a term of
    # evidence for a child who also sits in another one. `home_class_id` is
    # RESTRICT, so a class cannot be deleted while it is anyone's home.
    home_students: Mapped[list[Student]] = relationship(back_populates="home_class")

    # Everyone who sits in this class, home or visiting. This is what a roster,
    # a matrix, a tree and a printed pile all mean by "the students" — see
    # `class_service.list_students`.
    #
    # viewonly for the same reason `subjects` is: appending cannot assert that
    # the student shares this class's school AND school year, and that
    # assertion is I-platform-10. Writes go through `class_service.enroll`.
    roster: Mapped[list[Student]] = relationship(
        secondary=class_student,
        # CURRENTLY enrolled. `class_student` holds ended rows since 0027, and
        # this relationship keeps meaning exactly what it meant before that —
        # anything wanting the history asks `enrollment` for it with an `on`.
        primaryjoin=lambda: and_(
            Class.id == class_student.c.class_id,
            class_student.c.valid_to.is_(None),
        ),
        secondaryjoin=lambda: Student.id == class_student.c.student_id,
        order_by="Student.number",
        viewonly=True,
    )
    # The Branches this class studies — declared, not inferred. Until D57 this
    # was `SELECT DISTINCT sheet.subject_id`, which meant a brand-new class had
    # no Branch level to navigate at all until somebody built it a sheet.
    #
    # viewonly: appending here cannot know the next `position`, so writes go
    # through ``class_service.declare_subject`` instead.
    subjects: Mapped[list[Subject]] = relationship(
        secondary=class_subject, order_by=class_subject.c.position, viewonly=True
    )


class Person(Base, TimestampMixin, SchoolScopedMixin):
    """A pupil, across the years. Names, and nothing else.

    ``Student`` is a year-bound ENROLMENT record — uid, number, home class,
    school year — and before 0028 it was also the only identity there was, so a
    pupil's evidence reset every August in a product whose mastery model is
    explicitly about decay (D87). This row is what survives the summer, and it
    is the third instance of a split this codebase has already named twice:
    D56 for ``Chapter``, D69 for ``Student`` — where a row sits is a column,
    what it belongs to is a join. Here it is applied to time.

    Deliberately thin. Everything that is a fact about ONE YEAR — the uid the
    detector reads, the number the roster paste minted, the home class — stays
    on ``Student``, because a UID is a fact about one year's paper and must not
    change meaning. What hangs off this row is only what should outlive a year:
    ``Attempt``, ``MasterySnapshot``, ``MasteryBranchSnapshot``,
    ``MisconceptionNote``.

    No uniqueness on the names, and there must not be: homonyms are ordinary in
    a school of 400, and a constraint here would refuse the second Noah Favre.
    """

    __tablename__ = "person"

    id: Mapped[uuid.UUID] = _pk()
    # NULLABLE since 0032, which is what anonymisation means here: the names
    # go and nothing else does. A placeholder would have been a value in a
    # name column that every reader has to be told the meaning of; NULL says
    # "there is no name here" in the only way a database can.
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    # A parent's erasure request, answered by anonymisation: the names go, the
    # uid and the pedagogical record stay, so a class statistic does not change
    # shape underneath a band already shown to somebody. This is the fact a
    # screen reads — a null name is the consequence, this is the intent.
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Student(Base, TimestampMixin, SchoolScopedMixin):
    """Names are stored but NEVER required by any AI feature.

    ``uid`` (e.g. "7B_15") is the only identifier that leaves the database
    toward a model provider or onto a printed sheet. See docs/privacy.md.
    """

    __tablename__ = "student"
    # Covered by `uq_student_uid (school_id, school_year_id, uid)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        UniqueConstraint("school_id", "school_year_id", "uid", name="uq_student_uid"),
        CheckConstraint("number > 0", name="number_positive"),
    )

    id: Mapped[uuid.UUID] = _pk()
    # The class that MINTED this student's uid and number — not the set of
    # classes they attend, which is `class_student`. The split is D69, and it
    # is the same shape as `Chapter.primary_competency_id` (D56): where a row
    # sits is one fact, what it belongs to is another.
    #
    # RESTRICT, not the module's usual CASCADE: deleting a class must not
    # delete a child who also sits elsewhere, and deleting a student is the
    # only operation allowed to destroy attempts and snapshots.
    home_class_id: Mapped[uuid.UUID] = _fk("class.id", ondelete="RESTRICT")
    # WHO this enrolment record is for, across every year they are here. The
    # durable identity is `Person`; this row is one year of it (D87).
    #
    # CASCADE: deleting the identity deletes every year of enrolment and,
    # through them, the evidence. That is what keeps `delete_student` able to
    # destroy a pupil's record — it deletes the person once no other year
    # refers to them.
    person_id: Mapped[uuid.UUID] = _fk("person.id")
    school_year_id: Mapped[uuid.UUID] = _fk("school_year.id")
    uid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Also nullable, and it has to be: 0028 left a copy of the names on the
    # year-bound row, so anonymising only `person` would leave the name on
    # every roster and every printed sheet's instance list. Both go together
    # or neither does.
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))

    person: Mapped[Person] = relationship()
    home_class: Mapped[Class] = relationship(back_populates="home_students")
    # CURRENT enrollments. `scan_processing.wrong_class` reads this, so
    # widening it to the history would stop a pile flagging a page that no
    # longer belongs to it. A late scan of a copy sat before the pupil moved
    # is the case that deserves a historical read, and it is a separate
    # decision from what this relationship means (D87).
    classes: Mapped[list[Class]] = relationship(
        secondary=class_student,
        primaryjoin=lambda: and_(
            Student.id == class_student.c.student_id,
            class_student.c.valid_to.is_(None),
        ),
        secondaryjoin=lambda: Class.id == class_student.c.class_id,
        viewonly=True,
    )


# --------------------------------------------------------------------------
# Curriculum
# --------------------------------------------------------------------------
class Competency(Base, TimestampMixin):
    """Hierarchical, curriculum-coded. LP21 and PER coexist in one table.

    Not school-scoped: official curriculum data is shared reference data.
    """

    __tablename__ = "competency"
    __table_args__ = (
        UniqueConstraint("curriculum", "code", name="uq_competency_code"),
        Index("ix_competency_subject_cycle", "subject_key", "cycle"),
    )

    id: Mapped[uuid.UUID] = _pk()
    curriculum: Mapped[CurriculumKind] = mapped_column(
        Enum(CurriculumKind, name="curriculum_kind"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    # Indexed: the tree walks children-of-a-node, and `ondelete="SET NULL"`
    # makes Postgres find every child of a deleted competency — both of which
    # scan the table without this (M1).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="SET NULL"), index=True
    )
    subject_key: Mapped[str] = mapped_column(String(50), nullable=False)
    cycle: Mapped[int] = mapped_column(Integer, nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    description: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)

    children: Mapped[list[Competency]] = relationship()


chapter_competency = Table(
    "chapter_competency",
    Base.metadata,
    Column("chapter_id", PgUUID(as_uuid=True), ForeignKey("chapter.id", ondelete="CASCADE"), primary_key=True),
    Column("competency_id", PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True),
    # The other direction, for the same reason 0039 added it to
    # `exercise_competency`: the composite PK indexes
    # `(chapter_id, competency_id)` and answers only "what does this Theme
    # credit". "Which Themes credit this competency" — which is what deleting
    # a competency has to ask, and what a curriculum-first read asks — cannot
    # use an index whose leading column is the other one (M1).
    Index("ix_chapter_competency_competency_id", "competency_id"),
)

exercise_competency = Table(
    "exercise_competency",
    Base.metadata,
    Column("exercise_id", PgUUID(as_uuid=True), ForeignKey("exercise.id", ondelete="CASCADE"), primary_key=True),
    Column("competency_id", PgUUID(as_uuid=True), ForeignKey("competency.id", ondelete="CASCADE"), primary_key=True),
    # The composite PK indexes `(exercise_id, competency_id)` and so answers
    # "what does this exercise credit" for free. "Which exercises credit this
    # competency" is the other direction and gets nothing from it — and it is
    # the one the bank asks (`GET /exercises?competency_id=`), over the whole
    # school's corpus rather than one document.
    Index("ix_exercise_competency_competency", "competency_id"),
)


UNFILED_CHAPTER_KEY = "unfiled"
"""The Theme a sheet nobody has filed belongs to, one per subject.

``Sheet.chapter_id`` is NOT NULL, so a sheet always has a home; this is the
honest one to give it when the teacher has not chosen. Lives here rather than
in the seed loader because the read paths need the discriminator and a service
must not import the seeder to get it.

Note this key identifies the row; what keeps it OUT of the tree and the
roll-up is ``primary_competency_id IS NULL``. Those are deliberately two
different tests: a school may relabel the bucket, and a rename must not
readmit it to a mastery number.
"""


class Chapter(Base, TimestampMixin, SchoolScopedMixin):
    """The teacher's textbook-oriented grouping, mapped to competencies."""

    __tablename__ = "chapter"
    # Covered by `uq_chapter_key (school_id, subject_id, key)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        # A subject has ONE chapter per key, and in particular one `unfiled`
        # bucket. Without this, two concurrent "new sheet" calls in a subject
        # that has none yet both see nothing and both insert one, and the
        # subject's unfiled sheets then split silently across two buckets.
        UniqueConstraint("school_id", "subject_id", "key", name="uq_chapter_key"),
    )

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    # The single canonical parent this chapter HANGS FROM in the navigation
    # tree: Branch -> Competence -> Theme. The Competence node is this
    # competency's own ``parent_id`` (or itself, when the primary is already
    # top-level).
    #
    # Deliberately NOT the same thing as ``competencies`` below, and the
    # difference is the whole design (D56). ``competencies``
    # (chapter_competency) is the TAGGING set that mastery credit flows
    # through — one chapter legitimately spans two curricula, which is why
    # `plane_geometry_pythagoras` carries MSN 31.1, MSN 31.2, MA.2.A.2 and
    # MA.2.C.1 at once (docs/curriculum.md §3). Rolling the Competence level
    # up through that set would leak a chapter's evidence into branches its
    # primary never belongs to. This column is the narrower fact: ONE node,
    # resolved per school from ``School.default_curriculum`` at seed time, so
    # a Romand and a Deutschschweiz school file the same chapter under their
    # own official code without either needing a second column.
    #
    # NULL for the per-subject `unfiled` chapter and for nothing else. That is
    # what excludes it from the tree and from the roll-up — `tree_service`
    # filters on IS NOT NULL rather than string-matching ``key``, so a school
    # that renames the bucket cannot accidentally readmit it.
    primary_competency_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("competency.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    labels: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # selectin, like `primary_competency` below: `tree_service` walks this set
    # for every chapter of a branch to collect the competencies a Theme can
    # credit, which was one query per chapter under the default lazy load.
    competencies: Mapped[list[Competency]] = relationship(
        secondary=chapter_competency, lazy="selectin"
    )
    # selectin: the tree endpoint loads every chapter of a subject at once and
    # needs each one's parent to group by Competence. One extra query beats N.
    primary_competency: Mapped[Competency | None] = relationship(
        foreign_keys=[primary_competency_id], lazy="selectin"
    )


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
class Source(Base, TimestampMixin, SchoolScopedMixin):
    """An uploaded textbook / workbook PDF. Never redistributed by Alppy."""

    __tablename__ = "source"

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    uploaded_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the teacher calls this book. `filename` is what they happened to
    # upload ("scan 3 (copy).pdf"), which is provenance, not a name — and it
    # is the only thing the shelf could show before this column.
    title: Mapped[str | None] = mapped_column(String(200))
    # The bibliographic facts. All optional, and deliberately not validated
    # beyond length: a teacher typing what is on the cover of a cantonal
    # workbook should not be told their ISBN is malformed. Alppy never
    # redistributes the file, so these identify the book for a HUMAN deciding
    # whether two shelves hold the same one.
    publisher: Mapped[str | None] = mapped_column(String(200))
    isbn: Mapped[str | None] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    language: Mapped[str | None] = mapped_column(String(5))
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.QUEUED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)
    notice: Mapped[str | None] = mapped_column(Text)
    """A truthful caveat on an otherwise *successful* ingest.

    ``error`` explains a failure; this explains a success that is narrower than
    it looks — extraction skipped because no model is configured, or only the
    first N chunks scanned on a very long book. Without it the teacher reads a
    green tick and assumes the whole book was indexed for exercises."""

    chunks: Mapped[list[SourceChunk]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    sections: Mapped[list[SourceSection]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        order_by="SourceSection.position",
    )


class SourceSection(Base, TimestampMixin, SchoolScopedMixin):
    """A chapter of the uploaded document, as the document itself declares it.

    This is deliberately *not* ``Chapter``. A ``Chapter`` is the teacher's own
    grouping, mapped to curriculum competencies, and an exercise reaches one
    only by inference (``ingest.pipeline._chapter_for`` picks the chapter whose
    competencies overlap most, and returns ``None`` when the model tagged none).
    That inference needs three things to hold at once — the teacher has created
    chapters, those chapters carry competency codes, and the extraction tagged
    the item — so on a real textbook a large minority of rows end up untagged
    and unreachable by a chapter filter.

    A section is a fact about the file: "4 · Les fractions, p. 112–131". It
    needs no setup, it cannot be null for an exercise that came from a page, and
    it is how a teacher actually navigates a 400-page book. Both axes are
    offered in the builder; this one is the primary.

    ``extracted_at`` is the on-demand marker: ingestion maps every section and
    indexes every chunk, but a section's exercises are transcribed by the model
    only when a teacher first opens it. A book nobody teaches from costs nothing.
    """

    __tablename__ = "source_section"
    __table_args__ = (
        UniqueConstraint("source_id", "position", name="uq_source_section_position"),
        Index("ix_source_section_source", "source_id", "position"),
    )

    id: Mapped[uuid.UUID] = _pk()
    source_id: Mapped[uuid.UUID] = _fk(
        "source.id",
        index=False,  # covered by `ix_source_section_source`
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # The number the book prints ("4"), when one was found. Not the position:
    # a preface or an un-numbered appendix has a position but no label.
    label: Mapped[str | None] = mapped_column(String(20))
    page_from: Mapped[int] = mapped_column(Integer, nullable=False)
    page_to: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the model last read this section for exercises. ``None`` means
    indexed and searchable but never transcribed — the state the builder offers
    an "Extract" button for."""

    extraction_notice: Mapped[str | None] = mapped_column(Text)
    """A truthful caveat on an otherwise successful extraction of *this*
    section, mirroring ``Source.notice`` at section scale (no model configured,
    or the per-section chunk ceiling was hit)."""

    source: Mapped[Source] = relationship(back_populates="sections")


class SourceChunk(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "source_chunk"
    __table_args__ = (
        Index("ix_source_chunk_source_page", "source_id", "page"),
        # The index retrieval actually rides on (0042). `vector_cosine_ops`
        # because `retrieval.py` ranks with `cosine_distance` — an index built
        # for another operator class is not a slower index, it is an unused
        # one, and an unused index looks exactly like no index at all from the
        # outside.
        #
        # Declared here as well as in the migration so `check-schema-drift.py`
        # sees the two agree. The dialect kwargs are ignored off Postgres, so
        # the SQLite suite gets a plain index over the TEXT column its
        # test-only `@compiles` spells `embedding` as, which costs nothing and
        # keeps `create_all` honest about the index existing.
        Index(
            "ix_source_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    source_id: Mapped[uuid.UUID] = _fk(
        "source.id",
        index=False,  # covered by `ix_source_chunk_source_page`
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(_EMBED_DIM))

    source: Mapped[Source] = relationship(back_populates="chunks")


class Exercise(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "exercise"
    __table_args__ = (
        CheckConstraint("difficulty BETWEEN 1 AND 5", name="difficulty_range"),
        Index("ix_exercise_subject_origin", "subject_id", "origin"),
        # The builder's hot query: one section, ordered as the book prints it.
        Index("ix_exercise_source_section", "source_section_id", "source_page"),
        # Created in migration 0004 and declared nowhere until now, so
        # autogenerate proposed dropping it on every run. Partial on purpose:
        # the discarded rows are a small tail of the table, and the only query
        # that wants them is "what has this teacher already rejected for this
        # subject", which the next generation run asks so it does not offer the
        # same item twice.
        Index(
            "ix_exercise_discarded",
            "subject_id",
            postgresql_where=text("discarded_at IS NOT NULL"),
            sqlite_where=text("discarded_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    subject_id: Mapped[uuid.UUID] = _fk(
        "subject.id",
        index=False,  # covered by `ix_exercise_subject_origin`
    )
    chapter_id: Mapped[uuid.UUID | None] = _fk("chapter.id", nullable=True, ondelete="SET NULL")
    source_id: Mapped[uuid.UUID | None] = _fk("source.id", nullable=True, ondelete="SET NULL")
    source_chunk_id: Mapped[uuid.UUID | None] = _fk(
        "source_chunk.id", nullable=True, ondelete="SET NULL"
    )
    # The book's own chapter. Always set for an extracted exercise — the
    # unrecognised tail of a document gets a catch-all section rather than a
    # NULL, so no exercise is invisible to the builder's primary filter.
    source_section_id: Mapped[uuid.UUID | None] = _fk(
        "source_section.id",
        nullable=True,
        ondelete="SET NULL",
        index=False,  # covered by `ix_exercise_source_section`
    )
    source_page: Mapped[int | None] = mapped_column(Integer)
    # The book's own code and title for the exercise ("NO64", "Les quatre
    # multiplications"). Set by the region detector; NULL for anything a model
    # or a teacher wrote. This is how a teacher recognises an exercise, so the
    # builder shows it and the search matches it.
    label: Mapped[str | None] = mapped_column(String(16))
    title: Mapped[str | None] = mapped_column(String(200))
    # A crop of the page, exactly as printed: the figure, the table, the
    # fractions the text layer cannot carry. Stored in object storage under
    # ``figures/<school>/<source>/…``; the sheet prints it in place of the
    # statement and paginates on its physical size, which is why the size is
    # kept here in millimetres rather than re-read from the image.
    figure_key: Mapped[str | None] = mapped_column(String(500))
    figure_width_mm: Mapped[float | None] = mapped_column(Float)
    figure_height_mm: Mapped[float | None] = mapped_column(Float)

    type: Mapped[ExerciseType] = mapped_column(
        Enum(ExerciseType, name="exercise_type"), nullable=False
    )
    origin: Mapped[ExerciseOrigin] = mapped_column(
        Enum(ExerciseOrigin, name="exercise_origin"),
        default=ExerciseOrigin.TEXTBOOK,
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    answer_index: Mapped[int | None] = mapped_column(Integer)
    answer_bool: Mapped[bool | None] = mapped_column(Boolean)
    answer_text: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # AI-generated exercises are never printed without teacher approval.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A generated item the teacher threw away. Kept rather than deleted so the
    # next adaptive run knows not to propose it again (and so any Attempt that
    # already points at it still resolves).
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    competencies: Mapped[list[Competency]] = relationship(secondary=exercise_competency)

    @property
    def option_count(self) -> int:
        """How many bubbles this item gets on the printed answer grid."""
        if self.type is ExerciseType.TRUE_FALSE:
            return 2
        if self.type is ExerciseType.MCQ:
            # Capped at the grid width: the sheet only ever draws MAX_OPTIONS
            # bubbles, so claiming more would key an answer to a bubble that is
            # not on the paper. `sheets.pagination.Item.option_count` caps the
            # same way; the two must agree.
            from alppy.sheets.layout import MAX_OPTIONS

            return min(len(self.options or []), MAX_OPTIONS)
        return 0  # open: printed, no bubbles, never auto-graded


class ExerciseVariant(Base, TimestampMixin, SchoolScopedMixin):
    """A per-student generated version of an exercise (F4)."""

    __tablename__ = "exercise_variant"

    id: Mapped[uuid.UUID] = _pk()
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id")
    student_id: Mapped[uuid.UUID | None] = _fk("student.id", nullable=True)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    answer_index: Mapped[int | None] = mapped_column(Integer)
    answer_bool: Mapped[bool | None] = mapped_column(Boolean)
    explanation: Mapped[str | None] = mapped_column(Text)
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# --------------------------------------------------------------------------
# Sheets
# --------------------------------------------------------------------------
sheet_source = Table(
    "sheet_source",
    Base.metadata,
    Column("sheet_id", PgUUID(as_uuid=True), ForeignKey("sheet.id", ondelete="CASCADE"), primary_key=True),
    # SET NULL is not available on a composite primary key, so a source sheet
    # that is deleted takes the lineage row with it. The chain shortens; it
    # never points at a sheet that is gone.
    Column(
        "source_sheet_id",
        PgUUID(as_uuid=True),
        ForeignKey("sheet.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    # The order the teacher named them. `position` 0 is the PRINCIPAL, and is
    # the same sheet as `Sheet.derived_from_id` — one row, two access paths,
    # asserted in ``sheet_service.create_adaptive_sheet``.
    Column("position", Integer, nullable=False),
    Index("ix_sheet_source_source_sheet_id", "source_sheet_id"),
)
"""Every sheet whose corrected results justified this one.

``Sheet.derived_from_id`` answers "what does this sheet hang from" with exactly
one row — it is what the feedback page prints and what D61 validates. This
table answers the wider question: a reprise may answer a test *and* the two
earlier worksheets whose gaps it revisits, and before this there was nowhere to
say so. The split is D56's, applied a third time: where a row SITS is a column,
what it BELONGS TO is a join table (D70).
"""


class Sheet(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "sheet"
    __table_args__ = (
        # The barème is bounded so the printed "(N pts)" label has a known
        # widest form; `pagination.POINTS_LABEL_W_MM` reserves room for it.
        CheckConstraint(
            "default_points_correct BETWEEN 0 AND 20", name="ck_sheet_default_points_correct"
        ),
        CheckConstraint(
            "default_points_penalty BETWEEN 0 AND 20", name="ck_sheet_default_points_penalty"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    class_id: Mapped[uuid.UUID] = _fk("class.id")
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    # The Theme this sheet is filed under — a fact the teacher states, or that
    # ``create_sheet`` states for them by falling back to the subject's
    # `unfiled` chapter. Never inferred from the items: `Exercise.chapter_id`
    # is itself a guess (see SourceSection's docstring) and promoting a guess
    # into a teacher-facing filing the teacher never confirmed is exactly what
    # `approved_at` exists to prevent elsewhere.
    #
    # RESTRICT, not the module's usual CASCADE: a class's printed sheets,
    # scans and attempts must not evaporate because a chapter was deleted —
    # the same reasoning as ``SheetItem.exercise_id``.
    chapter_id: Mapped[uuid.UUID] = _fk("chapter.id", ondelete="RESTRICT")
    created_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target: Mapped[SheetTarget] = mapped_column(
        Enum(SheetTarget, name="sheet_target"), default=SheetTarget.CLASS, nullable=False
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    intent: Mapped[str | None] = mapped_column(Text)

    # The COMMON sheet whose corrected scan produced this one. NULL on every
    # sheet that is not an adaptive descendant. A teaching unit is a chain of
    # these: one common sheet, then the differentiated sheets its results
    # justify. Nothing else records that a sheet answers another one — without
    # it the two are just two rows with adjacent dates.
    derived_from_id: Mapped[uuid.UUID | None] = _fk(
        "sheet.id", ondelete="SET NULL", nullable=True
    )

    # The print layout and the scan detector are versioned together. A scan is
    # always registered against the layout the sheet was printed with.
    layout_version: Mapped[str] = mapped_column(String(10), default="v1", nullable=False)

    # The teacher's barème for this sheet: what a correct answer is worth and
    # what a wrong one costs. NOT NULL, because every item needs a value to
    # fall back to — a sheet item's own columns are the nullable ones. The
    # penalty is a MAGNITUDE; `scan.grading.score_for` applies the sign, so
    # "0.25" here always means a quarter point off, never a quarter point on.
    default_points_correct: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False, server_default=text("1")
    )
    default_points_penalty: Mapped[float] = mapped_column(
        Float, default=0.0, nullable=False, server_default=text("0")
    )

    blank_pdf_key: Mapped[str | None] = mapped_column(String(500))
    answer_key_pdf_key: Mapped[str | None] = mapped_column(String(500))
    # The feedback pages, as their OWN document. Deliberately not extra pages
    # inside the copy: the detector counts a copy's pages by re-paginating its
    # items (`scan_processing._copies_by_uid`), so a page the renderer adds and
    # that count does not know about shifts `seen[uid] % len(printed_pages)`
    # and grades page 2 against page 1's questions. A separate document cannot
    # do that, whatever happens to the feedback afterwards.
    feedback_pdf_key: Mapped[str | None] = mapped_column(String(500))
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the sheet actually went to the photocopier, which is not
    # `rendered_at`: a teacher renders on Sunday and prints on Tuesday. The
    # fact was only ever in the event log, so "has this been printed" meant
    # paging `/timeline` and reading somebody else's audit trail (audit 02,
    # M13). A column rather than a lookup because `sheet_out` is pure, and a
    # queried field would fan out one event query per row of `GET /sheets`.
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Bumped on every render. The answer-box rectangles a scan is cropped at
    #: belong to ONE render of this sheet, and `rendered_at` alone cannot say
    #: which: print on Tuesday, edit and re-render on Wednesday for an
    #: absentee, photograph Tuesday's copies on Thursday, and the crops land at
    #: Wednesday's geometry. `AnswerBoxPlacement` and `Scan` both carry this so
    #: the scan job can ask for the rectangles the paper in its hand was
    #: actually printed with — the same job `layout_version` already does for
    #: the layout dimension, and the same pinning pattern (B7).
    render_generation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    chapter: Mapped[Chapter] = relationship()
    items: Mapped[list[SheetItem]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan", order_by="SheetItem.position"
    )
    instances: Mapped[list[SheetInstance]] = relationship(
        back_populates="sheet", cascade="all, delete-orphan"
    )
    # The piles photographed against this sheet, oldest first. viewonly: a scan
    # is created by the upload path with its own school and storage keys, never
    # by appending to a sheet.
    scans: Mapped[list[Scan]] = relationship(
        primaryjoin="Sheet.id == Scan.sheet_id",
        order_by="Scan.created_at",
        viewonly=True,
    )
    # viewonly: appending cannot know the next `position`, and position 0 has
    # to stay in step with `derived_from_id`. Writes go through
    # ``sheet_service.set_sources``.
    sources: Mapped[list[Sheet]] = relationship(
        secondary=sheet_source,
        primaryjoin="Sheet.id == sheet_source.c.sheet_id",
        secondaryjoin="Sheet.id == sheet_source.c.source_sheet_id",
        order_by=sheet_source.c.position,
        viewonly=True,
    )


class SheetItem(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "sheet_item"
    __table_args__ = (
        UniqueConstraint("sheet_id", "position", name="uq_sheet_item_position"),
        # Any height up to the tallest box a page can carry on its own
        # (``layout.ANSWER_BOX_MAX_LINES``); 0 prints none. Taller would be a
        # box no page can hold, so pagination could never place it.
        CheckConstraint(
            "answer_box_lines IS NULL OR answer_box_lines BETWEEN 0 AND 14",
            name="ck_sheet_item_answer_box_lines",
        ),
        CheckConstraint(
            "points_correct IS NULL OR points_correct BETWEEN 0 AND 20",
            name="ck_sheet_item_points_correct",
        ),
        CheckConstraint(
            "points_penalty IS NULL OR points_penalty BETWEEN 0 AND 20",
            name="ck_sheet_item_points_penalty",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk(
        "sheet.id",
        index=False,  # covered by `uq_sheet_item_position`
    )
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id", ondelete="RESTRICT")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # The teacher may edit the printed wording without mutating the corpus.
    statement_override: Mapped[str | None] = mapped_column(Text)
    # The written-answer box under an `open` item: its height in 8 mm lines
    # (1 to 14; 0 prints none) and what is printed inside it. Per sheet item, not per
    # exercise, for the same reason as the wording: the same exercise may want
    # three lines on a quiz and twelve on a test. NULL means the default, and
    # both are meaningless on an MCQ or a true/false item.
    answer_box_lines: Mapped[int | None] = mapped_column(Integer)
    answer_box_fill: Mapped[AnswerBoxFill | None] = mapped_column(
        Enum(AnswerBoxFill, name="answer_box_fill")
    )
    # The answer the teacher expects for THIS printing of an open item. It is
    # what the answer key prints and what the vision grader judges against.
    # Per sheet item like the wording: a reworded statement wants a different
    # answer, and the corpus keeps the book's own. NULL falls back to the
    # exercise's `answer_text`; when that is NULL too, the grader works the
    # answer out itself before judging, and says so to the teacher.
    expected_answer: Mapped[str | None] = mapped_column(Text)
    # This item's own barème. NULL means "use the sheet's default" — the same
    # convention as `answer_box_lines`, and the reason 0.0 must be tested with
    # `is not None` rather than for truth: a deliberate 0 is a bonus item that
    # costs nothing to get wrong, not an absent override.
    #
    # Deliberately NOT gated by exercise type. The wording and the box are
    # meaningless on a bubble item, but a point value is meaningful on every
    # type — an `open` item is not auto-graded today and will be the moment a
    # verdict arrives through `register_grader`, and a column that had to be
    # un-gated later is worse than one that was never gated.
    points_correct: Mapped[float | None] = mapped_column(Float)
    points_penalty: Mapped[float | None] = mapped_column(Float)

    sheet: Mapped[Sheet] = relationship(back_populates="items")
    exercise: Mapped[Exercise] = relationship()


class SheetInstance(Base, TimestampMixin, SchoolScopedMixin):
    """One printed sheet bound to one student UID.

    For a differentiated batch each instance has its own item list (via
    ``item_plan``), which is why a class export is not simply N copies.
    """

    __tablename__ = "sheet_instance"
    __table_args__ = (UniqueConstraint("sheet_id", "student_id", name="uq_instance_student"),)

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk(
        "sheet.id",
        index=False,  # covered by `uq_instance_student`
    )
    student_id: Mapped[uuid.UUID] = _fk("student.id")
    student_uid: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # [{exercise_id, variant_id|null, position}] — resolved at render time.
    item_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    page_count: Mapped[int | None] = mapped_column(Integer)
    #: What this copy was worth, frozen when the pile was confirmed (B18).
    #:
    #: `points_earned` on a returned paper is the sum of `Attempt.score`, which
    #: was frozen at confirmation; `points_possible` was recomputed live from
    #: `SheetItem.points_correct` and `Sheet.default_points_correct` every time
    #: the report was opened. So editing the barème after a pile was confirmed
    #: silently rewrote the denominator of every paper already handed back —
    #: 14/20 became 14/25 with no record, on a sheet the class had taken home.
    #:
    #: Frozen **per copy** rather than per attempt, and that is a deliberate
    #: departure from the obvious place: an item the grader could not read
    #: produces no `Attempt` at all, so a sum over attempts would quietly leave
    #: those items out of what the paper was worth. This is the whole copy's
    #: total, over its own item plan, exactly as `_possible_by_student` computes
    #: it — captured at the one moment the number becomes a promise.
    #:
    #: NULL means "never confirmed", and the live computation still applies:
    #: a sheet being previewed or edited must show the barème as it stands now.
    points_possible: Mapped[float | None] = mapped_column(Float)

    # Which personalised group this copy belongs to, as a printable label
    # ("Groupe 2 · Fractions équivalentes"). A label rather than a foreign key
    # to a group entity: the grouping is recomputed from mastery every time the
    # teacher asks, so a stored group would be stale the moment the next scan
    # lands, and nothing downstream — mastery, attempts, scans — needs to know
    # a copy belonged to one.
    group_label: Mapped[str | None] = mapped_column(String(60))

    # This student's misconception note, bound when the batch is created.
    feedback_id: Mapped[uuid.UUID | None] = _fk(
        "misconception_note.id", ondelete="SET NULL", nullable=True
    )

    sheet: Mapped[Sheet] = relationship(back_populates="instances")
    feedback: Mapped[MisconceptionNote | None] = relationship()



class AnswerBoxPlacement(Base, TimestampMixin, SchoolScopedMixin):
    """Where one written-answer box actually printed, in page millimetres.

    Measured from the rendered document — never recomputed from the rows. A
    bubble sits at a coordinate the layout fixes, so the detector can derive it
    from the item index alone; a box sits under a statement whose height the
    browser decides, so the only honest source of its position is the render
    that went to the printer. Written wholesale when a sheet is rendered — and,
    since B7, kept **per render generation** rather than replaced outright.

    This docstring used to claim that "an exercise edited after the pile was
    printed cannot move the rectangle the scanner crops", and the delete-then-
    rewrite it described was precisely how an edit did move it: print on
    Tuesday, edit and re-render on Wednesday to run off a copy for an absentee,
    upload Tuesday's photographs on Thursday, and every one of them is cropped
    at Wednesday's geometry. The rows the pile was measured at had been deleted
    on Wednesday. Nothing recorded that, and a written answer cut at the wrong
    rows is graded on whatever ink the crop happened to contain.

    `Sheet.render_generation` counts renders; `Scan.render_generation` pins the
    one a pile was printed from, exactly as `layout_version` already pins the
    layout. Delete-and-rewrite still happens **within** one generation, which is
    what keeps the roster reasoning true — a re-render loses the rows of a child
    who left as surely as it gains those of one who arrived — while a *previous*
    generation's rectangles stay where they are, because a pile printed from
    them may not have been photographed yet.

    Keyed the way a detection is resolved: the render generation, the student's
    UID, which page of their copy, and the page-local item index.
    """

    __tablename__ = "answer_box_placement"
    __table_args__ = (
        # The generation is part of the slot since B7. Without it a second
        # render of the same sheet collides with the first on every box, which
        # is what forced the old delete-everything-and-rewrite and with it the
        # bug: keeping the rows was impossible, so the rectangles a printed
        # pile was measured at could not survive the next render.
        UniqueConstraint(
            "sheet_id", "render_generation", "student_uid", "copy_page", "item_index",
            name="uq_answer_box_placement_slot",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID] = _fk(
        "sheet.id",
        index=False,  # covered by `uq_answer_box_placement_slot`
    )
    #: Which render of the sheet measured this rectangle (B7). NULL is every
    #: row written before generations existed, and is matched only by a scan
    #: that also predates them — never by a later render's crops.
    render_generation: Mapped[int | None] = mapped_column(Integer)
    exercise_id: Mapped[uuid.UUID | None] = _fk(
        "exercise.id", nullable=True, ondelete="SET NULL"
    )
    student_uid: Mapped[str] = mapped_column(String(20), nullable=False)
    #: 1-based, the student's own folio — the same number the page footer prints.
    copy_page: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Page-local, 0..15 — what ``Detection.item_index`` carries.
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    box_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    box_fill: Mapped[AnswerBoxFill] = mapped_column(
        Enum(AnswerBoxFill, name="answer_box_fill"), nullable=False
    )
    x_mm: Mapped[float] = mapped_column(Float, nullable=False)
    y_mm: Mapped[float] = mapped_column(Float, nullable=False)
    w_mm: Mapped[float] = mapped_column(Float, nullable=False)
    h_mm: Mapped[float] = mapped_column(Float, nullable=False)
    layout_version: Mapped[str] = mapped_column(String(10), nullable=False)

class MisconceptionNote(Base, TimestampMixin, SchoolScopedMixin):
    """What one student got wrong on one common sheet, written for the student.

    A synthesis over several attempts rather than a fact about one, which is
    why it is not a column on ``Attempt``: "you subtract in the wrong order"
    is read off three wrong answers, and hanging it on an arbitrary one of them
    would make the other two look unexplained.

    It is not an ``ExerciseVariant`` either. That models a per-student rewrite
    of a *question*; this is prose about the student, addressed to them, with
    no question of its own.

    ``approved_at`` mirrors ``Exercise.approved_at`` and is enforced by the same
    module (`services.approval`). An unreviewed generated exercise is a bad
    question a teacher can spot on the page; an unreviewed generated note is a
    claim about how a named child thinks, handed to that child. The second
    needs the gate at least as much as the first.
    """

    __tablename__ = "misconception_note"
    __table_args__ = (
        Index("ix_misconception_note_person_sheet", "person_id", "based_on_sheet_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    person_id: Mapped[uuid.UUID] = _fk(
        "person.id",
        index=False,  # covered by `ix_misconception_note_person_sheet`
    )
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    # The common sheet the wrong answers came from. SET NULL rather than
    # CASCADE: deleting the sheet must not silently delete the explanation of
    # what a child misunderstood.
    based_on_sheet_id: Mapped[uuid.UUID | None] = _fk(
        "sheet.id", ondelete="SET NULL", nullable=True
    )
    language: Mapped[str] = mapped_column(String(5), nullable=False)
    # ["...", "..."] — one sentence group per misconception, printed in order.
    notes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # `'[]'` without the `::jsonb` cast the database stores it as. Postgres
    # coerces an untyped literal to the column's type and records the same
    # default either way; SQLite, where the suite builds its schema with
    # `create_all` (D18), renders whatever is written here verbatim into a
    # CREATE TABLE and chokes on the cast.
    competency_ids: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generation_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # The identity, not the year. What a note explains — a misconception a
    # child holds — is not a fact about one year's enrolment record (D87).
    person: Mapped[Person] = relationship()


class Event(Base, TimestampMixin, SchoolScopedMixin):
    """One thing that happened, append-only — the spine of the agenda.

    Why a log rather than more columns
    ----------------------------------
    Every row already carries ``created_at``/``updated_at``, and neither can
    answer the questions a teacher actually asks of a term. ``updated_at`` is
    overwritten by whatever edit came last, so it cannot say when a pile was
    confirmed; and two of the moments that matter most — a sheet going to the
    photocopier, a scan being confirmed — left no trace anywhere. Adding a
    column per moment would mean a migration every time the product learns a
    new verb, and would still not give one query that returns them in order.

    Append-only, deliberately. An event is a record that something happened; it
    is never corrected, only followed by another event. That is what makes the
    agenda trustworthy enough to answer "what did I actually do in March".

    ``occurred_at`` is separate from ``created_at`` because they are not always
    the same: a scan confirmed on Sunday evening carries the lesson's date, and
    a backfilled event carries the date of the thing it describes rather than
    the date the backfill ran.
    """

    __tablename__ = "event"
    # Covered by `ix_event_school_occurred (school_id, occurred_at)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        # The agenda's only query: this school, newest first.
        Index("ix_event_school_occurred", "school_id", "occurred_at"),
        Index("ix_event_subject", "subject_type", "subject_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[EventKind] = mapped_column(Enum(EventKind, name="event_kind"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Who did it. SET NULL: the record of the lesson outlives the account.
    actor_id: Mapped[uuid.UUID | None] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    subject_type: Mapped[EventSubject] = mapped_column(
        Enum(EventSubject, name="event_subject"), nullable=False
    )
    #: Deliberately NOT a foreign key. The log must outlive what it describes —
    #: a deleted sheet does not un-happen — and one column cannot point at four
    #: different tables. The agenda resolves the title itself and degrades to
    #: the stored summary when the row is gone.
    subject_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    class_id: Mapped[uuid.UUID | None] = _fk("class.id", ondelete="CASCADE", nullable=True)
    subject_area_id: Mapped[uuid.UUID | None] = _fk(
        "subject.id", ondelete="SET NULL", nullable=True
    )
    #: What to show when the subject row no longer exists. Never PII: a sheet
    #: title, a filename, a chapter — never a student name.
    # `server_default` as well as `default`, and the pair is not redundant:
    # `default` is Python's, applied by the ORM on an INSERT it builds, and
    # says nothing to a write that does not go through it — a migration's
    # backfill, a seed, a psql console. The database's own DEFAULT is the one
    # that covers those, and 0025 is the migration that exists because three
    # columns had only the first. Declared here so `check-schema-drift.py`,
    # which compares server defaults since audit H4, can see them agree.
    summary: Mapped[str] = mapped_column(
        String(200), nullable=False, default="", server_default=text("''")
    )
    #: Counts the agenda shows inline (pages, copies, exercises). No free text.
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


# --------------------------------------------------------------------------
# Scan and grading
# --------------------------------------------------------------------------
class Scan(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "scan"

    id: Mapped[uuid.UUID] = _pk()
    sheet_id: Mapped[uuid.UUID | None] = _fk("sheet.id", nullable=True, ondelete="SET NULL")
    uploaded_by_id: Mapped[uuid.UUID] = _fk("teacher.id", ondelete="SET NULL", nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # A phone upload is one file per copy: the teacher selects 28 photos and
    # expects ONE review session, not 28. Every uploaded file is stored, in the
    # order it was selected, and the pages of all of them concatenate into this
    # scan. ``storage_key`` stays as the first file so old rows keep working.
    storage_keys: Mapped[list[str] | None] = mapped_column(JSONB)
    # Set once from the sheet the pile was printed from, so a page is always
    # registered against the layout it was printed with (never the current one).
    layout_version: Mapped[str | None] = mapped_column(String(10))
    #: Which render of that sheet, pinned the same way and for the same reason
    #: (B7). NULL means a pile uploaded before generations existed: it matches
    #: the placements that also carry NULL, and never a later render's.
    render_generation: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status"), default=ScanStatus.UPLOADED, nullable=False
    )
    error: Mapped[str | None] = mapped_column(Text)

    # --- the confirmation history ------------------------------------------
    # A pile can be signed off, reopened, and signed off again. That is a fact
    # about its HISTORY, not a fourth status: `status` answers one question —
    # "is this pile signed off?" — and a revised pile still answers yes. Adding
    # a REVISED member would turn every `is ScanStatus.CONFIRMED` check in the
    # codebase into a two-member test, and each one missed is a silently
    # unlocked pile. The label the teacher reads is derived instead (D48):
    #   needs_review, count == 0 -> pending
    #   confirmed,    count == 1 -> validated
    #   confirmed,    count  > 1 -> revised
    #   needs_review, count  > 0 -> reopened
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Stamped by every successful confirmation, and NOT cleared on reopen.
    This is what orders "the newest other scan still confirmed" when a reopen
    has to decide which reading a freed item falls back to."""
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmation_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default=text("0")
    )

    pages: Mapped[list[ScanPage]] = relationship(
        back_populates="scan", cascade="all, delete-orphan", order_by="ScanPage.page_index"
    )


class ScanPage(Base, TimestampMixin, SchoolScopedMixin):
    __tablename__ = "scan_page"

    id: Mapped[uuid.UUID] = _pk()
    scan_id: Mapped[uuid.UUID] = _fk("scan.id")
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # Filled once the four fiducials are located and the page is deskewed.
    registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    registration_meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detected_uid: Mapped[str | None] = mapped_column(String(20), index=True)
    uid_confidence: Mapped[float | None] = mapped_column(Float)
    student_id: Mapped[uuid.UUID | None] = _fk("student.id", nullable=True, ondelete="SET NULL")
    sheet_instance_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_instance.id", nullable=True, ondelete="SET NULL"
    )
    # The UID decoded to a real student who is not in this sheet's class: last
    # week's pile got shuffled into this one. Not an error, but never silently
    # part of this sheet either.
    wrong_class: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # A cover sheet, a lens-cap frame, a page re-shot later. Discarded pages are
    # kept for audit and ignored by confirmation, so one bad photo cannot hold
    # a whole class set hostage.
    discarded: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    # Which page of that student's copy this is, resolved from the decoded UID.
    page_in_copy: Mapped[int | None] = mapped_column(Integer)

    scan: Mapped[Scan] = relationship(back_populates="pages")
    detections: Mapped[list[Detection]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class Detection(Base, TimestampMixin, SchoolScopedMixin):
    """One item's reading on one scanned page, before the teacher confirms."""

    __tablename__ = "detection"

    id: Mapped[uuid.UUID] = _pk()
    scan_page_id: Mapped[uuid.UUID] = _fk("scan_page.id")
    sheet_item_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_item.id", nullable=True, ondelete="SET NULL"
    )
    # The exercise this reading is graded against, resolved from the copy the
    # page belongs to. Stored rather than derived: a differentiated copy prints
    # its own item list, so "item 3 of the sheet" is not "item 3 of this paper".
    exercise_id: Mapped[uuid.UUID | None] = _fk(
        "exercise.id", nullable=True, ondelete="SET NULL"
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # The number printed beside the statement AND beside the grid row, counting
    # across the whole copy. item_index restarts at 0 on every physical page, so
    # it is not what the student's paper says next to the question.
    printed_number: Mapped[int | None] = mapped_column(Integer)
    detected_index: Mapped[int | None] = mapped_column(Integer)
    detected_bool: Mapped[bool | None] = mapped_column(Boolean)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    outcome: Mapped[DetectionOutcome] = mapped_column(
        Enum(DetectionOutcome, name="detection_outcome"), nullable=False
    )
    # What the MACHINE read, written once and never updated. A teacher override
    # goes into detected_*/outcome/confidence above; these three keep the
    # reading it replaced, because "the teacher disagreed with the scanner" is
    # the fact worth auditing and it is unrecoverable once overwritten.
    machine_index: Mapped[int | None] = mapped_column(Integer)
    machine_outcome: Mapped[DetectionOutcome | None] = mapped_column(
        Enum(DetectionOutcome, name="detection_outcome")
    )
    machine_confidence: Mapped[float | None] = mapped_column(Float)
    # Per-bubble fill ratios, kept so the review overlay can explain itself.
    fill_ratios: Mapped[list[float] | None] = mapped_column(JSONB)
    # Normalised [0,1] frame coords so the overlay scales to any rendered size.
    bubble_boxes: Mapped[list[dict[str, float]] | None] = mapped_column(JSONB)
    # A written answer. ``crop_key`` is the box cut from the registered page
    # with the printed furniture removed, stored beside the page image. The
    # transcription and the verdict follow the same split as the bubbles: the
    # current value the teacher may overwrite, and the machine's, written once.
    crop_key: Mapped[str | None] = mapped_column(String(500))
    transcription: Mapped[str | None] = mapped_column(Text)
    machine_transcription: Mapped[str | None] = mapped_column(Text)
    verdict_correct: Mapped[bool | None] = mapped_column(Boolean)
    machine_verdict_correct: Mapped[bool | None] = mapped_column(Boolean)
    # Which model read it, for the audit trail; never the prompt or the image.
    #
    # Since B19 this is the model that ANSWERED, taken from the response, not
    # the one that was configured. An alias like `claude-sonnet-5` resolves to a
    # dated build that changes underneath it, so a disputed grade traced back to
    # the configured string named a model that may never have seen the paper.
    vision_model: Mapped[str | None] = mapped_column(String(80))
    #: Which version of the grading prompt produced this verdict (B19).
    #:
    #: The model id alone does not identify the judgement: the same model under
    #: `grade_open_answer.v2` and `.v3` is told different things about what
    #: counts and what an instruction in the answer box means. A grade contested
    #: months later has to be traceable to the exact pair, and prompt versions
    #: are precisely the thing that moves between a mark and the appeal.
    vision_prompt_version: Mapped[str | None] = mapped_column(String(20))
    # What the grader judged against. The teacher's expected answer when one
    # existed; otherwise the answer the model worked out itself, kept so the
    # teacher reviewing the verdict can see what it was measured against.
    reference_answer: Mapped[str | None] = mapped_column(Text)
    corrected_by_id: Mapped[uuid.UUID | None] = _fk(
        "teacher.id", nullable=True, ondelete="SET NULL"
    )
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    page: Mapped[ScanPage] = relationship(back_populates="detections")
    # selectin, not joined: the review screen loads every detection of a scan at
    # once, so one extra query beats a row per detection.
    exercise: Mapped[Exercise | None] = relationship(lazy="selectin")
    sheet_item: Mapped[SheetItem | None] = relationship(lazy="selectin")


class Attempt(Base, TimestampMixin, SchoolScopedMixin):
    """A graded result: one student, one exercise, one confirmed sheet."""

    __tablename__ = "attempt"
    __table_args__ = (
        Index("ix_attempt_person_answered", "person_id", "answered_at"),
        # Re-scanning a pile must correct the record, not double it: mastery is
        # a weighted mean over attempts, so a duplicate silently doubles one
        # lesson's weight against every other. confirm_scan supersedes rather
        # than inserts; this is the backstop that makes that a guarantee.
        UniqueConstraint(
            "person_id", "exercise_id", "sheet_id", name="uq_attempt_person_exercise_sheet"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    person_id: Mapped[uuid.UUID] = _fk(
        "person.id",
        index=False,  # covered by `ix_attempt_person_answered`
    )
    exercise_id: Mapped[uuid.UUID] = _fk("exercise.id", ondelete="RESTRICT")
    sheet_id: Mapped[uuid.UUID | None] = _fk("sheet.id", nullable=True, ondelete="SET NULL")
    sheet_instance_id: Mapped[uuid.UUID | None] = _fk(
        "sheet_instance.id", nullable=True, ondelete="SET NULL"
    )
    detection_id: Mapped[uuid.UUID | None] = _fk(
        "detection.id", nullable=True, ondelete="SET NULL"
    )
    # Which confirmation wrote this row. Without it, reopening a pile has no
    # way to know which attempts it owns: `detection_id` names the reading, but
    # the same row may have been superseded from another scan since.
    confirmed_scan_id: Mapped[uuid.UUID | None] = _fk(
        "scan.id", nullable=True, ondelete="SET NULL"
    )
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MasterySnapshot(Base, TimestampMixin, SchoolScopedMixin):
    """student x competency x time. Recomputed after every confirmed scan."""

    __tablename__ = "mastery_snapshot"

    # No RETURNING on insert. `TimestampMixin` gives every table a
    # `server_default`, and SQLAlchemy fetches those back eagerly — which turns
    # a bulk snapshot write into INSERT ... RETURNING and hands it to the
    # `insertmanyvalues` correlation machinery. On SQLite that path
    # intermittently applies the wrong result processor and fails with
    # `'float' object has no attribute 'replace'`. These two tables are written
    # in bulk after every confirmed scan and their timestamps are never read
    # back in the same transaction, so there is nothing to fetch eagerly.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012  (read once, never mutated)
    __table_args__ = (
        Index("ix_mastery_person_competency", "person_id", "competency_id", "computed_at"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_unit_interval"),
    )

    id: Mapped[uuid.UUID] = _pk()
    person_id: Mapped[uuid.UUID] = _fk(
        "person.id",
        index=False,  # covered by `ix_mastery_person_competency`
    )
    competency_id: Mapped[uuid.UUID] = _fk("competency.id")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[MasteryBand] = mapped_column(
        Enum(MasteryBand, name="mastery_band"), nullable=False
    )
    attempts_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MasteryBranchSnapshot(Base, TimestampMixin, SchoolScopedMixin):
    """student x branch x time — a CACHE for the history curve, never a truth.

    A SEPARATE table, not a nullable `competency_id` on `MasterySnapshot`:
    making that column optional would turn every `(student, competency)` key in
    `latest_snapshots` into an optional and let I-mastery-07's "one row per
    student, competency, day" silently admit two kinds of row.

    **Nothing reads this to answer "what is this child's band".** Every read
    path recomputes from `Attempt`s, because the score decays with time — a
    matrix opened on Friday must not show Monday's numbers (`data-model.md`
    §4). This exists so a *curve* has points to draw and a dashboard has
    something cheap to sort by; both are historical questions, and history is
    the one thing recomputation cannot give you.

    It carries its own coverage. A branch band over one assessed competency
    and one over three are different claims, and a cached number that dropped
    the denominator would be the exact dishonesty DC-content-07 forbids on
    screen (I-mastery-12).
    """

    __tablename__ = "mastery_branch_snapshot"

    # No RETURNING on insert. `TimestampMixin` gives every table a
    # `server_default`, and SQLAlchemy fetches those back eagerly — which turns
    # a bulk snapshot write into INSERT ... RETURNING and hands it to the
    # `insertmanyvalues` correlation machinery. On SQLite that path
    # intermittently applies the wrong result processor and fails with
    # `'float' object has no attribute 'replace'`. These two tables are written
    # in bulk after every confirmed scan and their timestamps are never read
    # back in the same transaction, so there is nothing to fetch eagerly.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012  (read once, never mutated)
    __table_args__ = (
        Index("ix_mastery_branch_person", "person_id", "subject_id", "computed_at"),
        CheckConstraint(
            "score >= 0 AND score <= 1", name="branch_score_unit_interval"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    person_id: Mapped[uuid.UUID] = _fk(
        "person.id",
        index=False,  # covered by `ix_mastery_branch_person`
    )
    subject_id: Mapped[uuid.UUID] = _fk("subject.id")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[MasteryBand] = mapped_column(
        Enum(MasteryBand, name="mastery_band"), nullable=False
    )
    #: How much of the branch this number stands on. Never rendered without
    #: both, and never stored without both.
    child_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assessed_child_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------
class ModelCall(Base, TimestampMixin, SchoolScopedMixin):
    """Audit log of every model call. Contains NO student PII by construction.

    ``prompt_sha256`` lets us prove which prompt ran without storing content.
    """

    __tablename__ = "model_call"

    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_estimate_chf: Mapped[float | None] = mapped_column(Float)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class AdaptiveProposal(Base, TimestampMixin, SchoolScopedMixin):
    """The proposal a ``PROPOSE_ADAPTIVE`` job built, waiting to be read once.

    Not ``Job.result``. A class of twenty-four with eight items each — full
    statements, options, provenance — is close to a megabyte of JSON, and the
    review screen polls the job every 900 ms while it runs. Putting it in the
    status row would re-serialise the whole proposal on every poll to answer a
    question about progress.

    Not a set of durable rows either: the *exercises* are already persisted and
    approval already hangs off them. This is the shape of one screen, keyed by
    the job that produced it, read once and then stale — which is why it is its
    own table with its own lifetime rather than a column on something long-lived.
    """

    __tablename__ = "adaptive_proposal"

    id: Mapped[uuid.UUID] = _pk()
    job_id: Mapped[uuid.UUID] = _fk("job.id", ondelete="CASCADE")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (UniqueConstraint("job_id", name="uq_adaptive_proposal_job"),)


class PromptLog(Base, TimestampMixin, SchoolScopedMixin):
    """The full text of a model call, for debugging. Off unless a school asks.

    Deliberately NOT ``ModelCall``. That table is the audit trail: content-free
    by construction, safe to keep indefinitely, and what a DPO or auditor is
    shown to answer "did any of our data go to provider X" (docs/privacy.md §3).
    Putting prompt text in it would make the audit log the leak it exists to
    detect. This is the other thing — an engineer's window on what was actually
    sent — and it earns a different lifetime, a different default and a
    different consent story.

    Three properties it must keep:

    * **Off by default** (``ALPPY_AI_PROMPT_LOG_ENABLED``). A school opts in.
    * **Written only after the PII gate passed.** A prompt that fired
      ``PiiLeakError`` is by definition the one carrying a roster name; that row
      records the refusal and no content at all.
    * **Swept.** ``ALPPY_AI_PROMPT_LOG_RETENTION_DAYS`` and
      ``python -m alppy.cli purge-prompt-logs``. Passing the gate is not the same
      as containing no student data: a UID plus a class roster re-identifies, and
      a wrong answer is a fact about a child.

    ``model_call_id`` ties a row to its content-free twin, so an auditor reading
    ``model_call`` alone still sees a complete list of calls.
    """

    __tablename__ = "prompt_log"
    # Covered by `ix_prompt_log_school_created (school_id, created_at)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        Index("ix_prompt_log_school_created", "school_id", "created_at"),
        Index("ix_prompt_log_purpose_created", "purpose", "created_at"),
        Index("ix_prompt_log_request", "request_id"),
    )

    id: Mapped[uuid.UUID] = _pk()
    model_call_id: Mapped[uuid.UUID | None] = _fk(
        "model_call.id", nullable=True, ondelete="SET NULL"
    )
    job_id: Mapped[uuid.UUID | None] = _fk("job.id", nullable=True, ondelete="SET NULL")
    sheet_id: Mapped[uuid.UUID | None] = _fk("sheet.id", nullable=True, ondelete="SET NULL")
    request_id: Mapped[str | None] = mapped_column(String(64))
    """Correlates the calls of one propose run, one ingest, one grading pass.

    A string rather than a foreign key because the unit of work is not always a
    row: a synchronous request has no ``Job``."""

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_name: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(20))
    prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    system_text: Mapped[str | None] = mapped_column(Text)
    user_text: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Job(Base, TimestampMixin, SchoolScopedMixin):
    """Background work. Request handlers never block on a model call."""

    __tablename__ = "job"

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[JobKind] = mapped_column(Enum(JobKind, name="job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.QUEUED, nullable=False
    )
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    message: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Whose work this is and what it is for. Columns rather than keys read back
    # out of `payload`: a job was tenant-grained only, so the in-flight guard on
    # `/adaptive/propose` matched a colleague's run and handed back their job,
    # and `/adaptive/proposal/{job_id}` then served their per-pupil plan to
    # anyone in the school (audit 02, C1). Nullable because most kinds are not
    # about one class — a source ingest belongs to the staffroom corpus.
    class_id: Mapped[uuid.UUID | None] = _fk("class.id", nullable=True)
    subject_id: Mapped[uuid.UUID | None] = _fk("subject.id", nullable=True)
    # SET NULL, not CASCADE: a teacher leaving the school must not take the
    # audit trail of the work they queued with them.
    created_by_id: Mapped[uuid.UUID | None] = _fk(
        "teacher.id", nullable=True, ondelete="SET NULL"
    )
    # The pile this job is about, for the two kinds that have one. A column
    # because `grading_in_progress` had to load EVERY live job in the
    # deployment and match `payload["scan_id"]` in Python to answer "is a
    # grader still coming for this scan?" — a question asked on every
    # confirmation, answered by a scan of another tenant's rows, and the reason
    # confirmation could be blocked by a job nobody could see (audit 03, B26).
    scan_id: Mapped[uuid.UUID | None] = _fk("scan.id", nullable=True, ondelete="CASCADE")


class IdempotencyKey(Base, TimestampMixin, SchoolScopedMixin):
    """One remembered answer to one write, so a retry does not do it twice.

    Nothing in the product was idempotent (audit 03, B17). A phone on a flaky
    staffroom connection retries a POST it never saw answered; a teacher
    double-taps "print" because nothing moved yet. Both produced a second
    render job, a second batch of unapproved exercises, a second pile — and the
    endpoints that did guard against it did so ad hoc, each with its own
    in-flight query and its own idea of what "the same request" meant.

    The key is **claimed before the work runs**, not written after it. That
    ordering is the whole design: two simultaneous retries race on the unique
    constraint, exactly one wins the insert, and the loser can be told the work
    is already happening instead of doing it again. A row written afterwards
    would let both requests through and remember only the second.

    ``response`` is the body the first attempt answered with, replayed verbatim
    to every retry. NULL means the work is still running.

    Per tenant, and that is not decoration: keying on ``(endpoint, key)`` alone
    would let one school probe another's keyspace by guessing, and learn from a
    409 that a particular request had been made.

    ``POST /scans/{id}/confirm`` deliberately does NOT use this. It is already
    idempotent the better way — by superseding rather than accumulating — and
    it is the pattern the others should grow towards, not something to wrap.
    """

    __tablename__ = "idempotency_key"
    # Covered by `uq_idempotency_key (school_id, ...)` — see `SchoolScopedMixin` (M2).
    __school_id_index__ = False
    __table_args__ = (
        UniqueConstraint("school_id", "endpoint", "key", name="uq_idempotency_key"),
        Index("ix_idempotency_key_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = _pk()
    #: The route, as a stable name rather than a path — a path carries ids, and
    #: two renders of two different sheets are not the same request.
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    #: What the first attempt answered. NULL while it is still in flight.
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


__all__ = [
    "UNFILED_CHAPTER_KEY",
    "AdaptiveProposal",
    "AnswerBoxPlacement",
    "Attempt",
    "Base",
    "Chapter",
    "Class",
    "Competency",
    "Detection",
    "Event",
    "Exercise",
    "ExerciseVariant",
    "IdempotencyKey",
    "Job",
    "MasteryBranchSnapshot",
    "MasterySnapshot",
    "MisconceptionNote",
    "ModelCall",
    "PromptLog",
    "Scan",
    "ScanPage",
    "School",
    "SchoolYear",
    "Sheet",
    "SheetInstance",
    "SheetItem",
    "SheetKind",
    "Source",
    "SourceChunk",
    "Student",
    "Subject",
    "Teacher",
    "chapter_competency",
    "class_student",
    "class_subject",
    "class_teacher_subject",
    "exercise_competency",
    "sheet_source",
    "teacher_school",
]
