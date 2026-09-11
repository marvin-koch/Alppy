"""0027 makes a membership an interval. Nothing else can prove the backfill.

This is one of the two Critical fixes from the first audit in this series, and
it is exactly the kind of change no existing test can see. The unit suite
builds its schema with ``create_all()`` from the models, so it starts in a
world where memberships have always had ``valid_from``/``valid_to`` and never
replays the step that put them there. ``check-schema-drift.py`` replays every
migration but compares only the final *shape* — a backfill that set
``valid_from`` to the wrong date, or to nothing, ends with a shape that matches
the models perfectly.

Three claims are tested here, and each one is a sentence the migration's own
docstring makes:

1. **"the partial unique index keeps 'at most one CURRENT membership' true,
   which the widened key on its own does not."** Without it, two rows differing
   only in ``valid_from`` are both open, and that pupil is counted twice in
   every roster join and every matrix column.
2. **"After the backfill every row is open, so ``valid_to IS NULL`` selects
   exactly the rows an unqualified read selected before."** The
   behaviour-preservation claim, which is what lets the release ship without
   invalidating a session or moving a pupil.
3. **"The cast is ``(enrolled_at AT TIME ZONE 'UTC')::date`` rather than a bare
   ``::date``."** A bare cast resolves through the session's ``TimeZone``, so a
   membership created late in the evening gets a different ``valid_from``
   depending on who ran the migration — a difference that is invisible on the
   day and permanent afterwards.

And the downgrade is asserted too, because it is deliberately lossy in one
specific place and silently wrong in that place would be worse than failing.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
import sqlalchemy as sa
from migration_harness import (
    SERVER_URL,
    SKIP_REASON,
    alembic_at,
    disposable_database,
    require_or_skip,
)

from alembic import command

require_or_skip("migration 0027")

pytestmark = pytest.mark.skipif(SERVER_URL is None, reason=SKIP_REASON)


@pytest.fixture
def db_url() -> Iterator[str]:
    yield from disposable_database()



def _seed_at_0026(conn: sa.Connection) -> dict[str, uuid.UUID]:
    """A world in the OLD shape: memberships with a start and no end.

    Written in raw SQL against the pre-0027 columns rather than through the
    ORM, because the ORM models describe the world *after* this migration — a
    fixture built from them could not express the state being migrated from.

    The evening enrolment is the interesting row. 22:30 UTC is the next day in
    Europe/Zurich for half the year, so it is the one membership whose
    ``valid_from`` differs depending on whether the cast respects UTC.
    """
    ids = {
        k: uuid.uuid4()
        for k in ("school", "year", "teacher", "maths", "7B", "lea", "noah", "evening")
    }
    conn.execute(
        sa.text(
            "INSERT INTO school (id, name, canton, default_curriculum, created_at, updated_at)"
            " VALUES (:i, 'CO de Sion', 'VS', 'PER', now(), now())"
        ),
        {"i": ids["school"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO school_year (id, school_id, label, starts_on, ends_on,"
            " is_current, created_at, updated_at)"
            " VALUES (:i, :s, '2026/27', '2026-08-01', '2027-07-31', true, now(), now())"
        ),
        {"i": ids["year"], "s": ids["school"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO teacher (id, home_school_id, email, password_hash, first_name,"
            " last_name, locale, created_at, updated_at)"
            " VALUES (:i, :s, 'rossier@sion.ch', 'x', 'Marc', 'Rossier', 'FR', now(), now())"
        ),
        {"i": ids["teacher"], "s": ids["school"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO subject (id, school_id, key, labels, created_at, updated_at)"
            " VALUES (:i, :s, 'mathematics', '{\"fr\": \"Mathematiques\"}'::jsonb, now(), now())"
        ),
        {"i": ids["maths"], "s": ids["school"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO class (id, school_id, school_year_id, head_teacher_id, code,"
            " kind, created_at, updated_at)"
            " VALUES (:i, :s, :y, :t, '7B', 'homeroom', now(), now())"
        ),
        {"i": ids["7B"], "s": ids["school"], "y": ids["year"], "t": ids["teacher"]},
    )
    for key, uid, number, first, last in (
        ("lea", "7B_01", 1, "Lea", "Roth"),
        ("noah", "7B_02", 2, "Noah", "Berger"),
        ("evening", "7B_03", 3, "Mia", "Keller"),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO student (id, school_id, home_class_id, school_year_id, uid,"
                " number, first_name, last_name, created_at, updated_at)"
                " VALUES (:i, :s, :c, :y, :u, :n, :f, :l, now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "c": ids["7B"], "y": ids["year"],
                "u": uid, "n": number, "f": first, "l": last,
            },
        )

    # Two ordinary daytime enrolments, and one at 22:30 UTC — which is the
    # following day in Europe/Zurich, and therefore the row that tells the two
    # casts apart.
    for key, enrolled_at in (
        ("lea", "2026-08-20 09:00:00+00"),
        ("noah", "2026-08-20 09:00:00+00"),
        ("evening", "2026-09-15 22:30:00+00"),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO class_student (class_id, student_id, enrolled_at)"
                " VALUES (:c, :s, :e)"
            ),
            {"c": ids["7B"], "s": ids[key], "e": enrolled_at},
        )
    # A branch has to be declared on the class before a teacher can be assigned
    # to it: `fk_class_teacher_subject_class_subject` is a composite FK onto
    # `class_subject`, which is what stops a teacher holding a branch the class
    # does not teach.
    conn.execute(
        sa.text(
            "INSERT INTO class_subject (class_id, subject_id, position)"
            " VALUES (:c, :b, 0)"
        ),
        {"c": ids["7B"], "b": ids["maths"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO class_teacher_subject (class_id, teacher_id, subject_id, assigned_at)"
            " VALUES (:c, :t, :b, '2026-08-20 09:00:00+00')"
        ),
        {"c": ids["7B"], "t": ids["teacher"], "b": ids["maths"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO teacher_school (teacher_id, school_id, joined_at)"
            " VALUES (:t, :s, '2026-08-01 09:00:00+00')"
        ),
        {"t": ids["teacher"], "s": ids["school"]},
    )
    return ids


def _roster(conn: sa.Connection, class_id: uuid.UUID, *, open_only: bool) -> set[uuid.UUID]:
    """Who is in this class — the old way (every row) or the new way (open rows)."""
    predicate = " AND valid_to IS NULL" if open_only else ""
    return set(
        conn.execute(
            sa.text(f"SELECT student_id FROM class_student WHERE class_id = :c{predicate}"),
            {"c": class_id},
        ).scalars()
    )


# --- Claim 2: the backfill changes nobody's membership ----------------------


def test_an_all_open_table_reads_identically_before_and_after(db_url: str) -> None:
    """The migration's own behaviour-preservation claim.

    If this fails, a release that was supposed to be invisible has moved
    children between rosters.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0026")
            with engine.begin() as conn:
                ids = _seed_at_0026(conn)
                before = _roster(conn, ids["7B"], open_only=False)
            assert before == {ids["lea"], ids["noah"], ids["evening"]}

            command.upgrade(cfg, "0027")

            with engine.connect() as conn:
                after = _roster(conn, ids["7B"], open_only=True)
                assert after == before, "0027 changed who is enrolled in 7B"
                still_open = conn.execute(
                    sa.text("SELECT count(*) FROM class_student WHERE valid_to IS NOT NULL")
                ).scalar_one()
                assert still_open == 0, "the backfill closed a membership nobody ended"
        finally:
            engine.dispose()


# --- Claim 3: the date comes from UTC, not from whoever ran the migration ---


def test_valid_from_is_the_utc_date_of_the_start_column(db_url: str) -> None:
    """22:30 UTC on the 15th is the 15th, even when the session says Zurich.

    A bare ``::date`` resolves through the session's ``TimeZone``, so this row
    would become the 16th for anyone running the migration from a Swiss
    console and the 15th in CI. The value is written once and never
    recomputed, so the disagreement is permanent and silent.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0026")
            with engine.begin() as conn:
                ids = _seed_at_0026(conn)

            # The session a Swiss developer would have. It has to be set on the
            # DATABASE, not on this connection: `command.upgrade` opens its own,
            # which would otherwise inherit the server default and never see
            # Zurich — a `SET TIME ZONE` here makes the test pass against a bare
            # cast, which is the failure this test exists to catch.
            admin = sa.create_engine(db_url, isolation_level="AUTOCOMMIT")
            try:
                with admin.connect() as conn:
                    conn.execute(
                        sa.text(
                            f'ALTER DATABASE "{engine.url.database}" '
                            "SET TimeZone = 'Europe/Zurich'"
                        )
                    )
            finally:
                admin.dispose()
            command.upgrade(cfg, "0027")

            with engine.connect() as conn:
                conn.execute(sa.text("SET TIME ZONE 'Europe/Zurich'"))
                rows = dict(
                    conn.execute(
                        sa.text("SELECT student_id, valid_from FROM class_student")
                    ).all()
                )
            assert rows[ids["lea"]] == date(2026, 8, 20)
            assert rows[ids["evening"]] == date(2026, 9, 15), (
                "a 22:30 UTC enrolment became the next day: the cast resolved "
                "through the session timezone instead of UTC"
            )
        finally:
            engine.dispose()


# --- Claim 1: the partial unique index, on all three tables -----------------


@pytest.mark.parametrize(
    ("table", "columns"),
    [
        ("class_student", "class_id, student_id, enrolled_at"),
        ("class_teacher_subject", "class_id, teacher_id, subject_id, assigned_at"),
        ("teacher_school", "teacher_id, school_id, joined_at"),
    ],
)
def test_two_open_memberships_for_the_same_pair_are_refused(
    db_url: str, table: str, columns: str
) -> None:
    """The guarantee the widened primary key does NOT give.

    ``(class_id, student_id, valid_from)`` happily admits two rows that differ
    only in ``valid_from`` — and if both have ``valid_to IS NULL`` that pupil
    is enrolled twice, today. They are counted twice in every roster join and
    appear twice in every matrix column, which is a wrong number on a screen
    with no error anywhere near it.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0026")
            with engine.begin() as conn:
                ids = _seed_at_0026(conn)
            command.upgrade(cfg, "0027")

            values = {
                "class_student": (ids["7B"], ids["lea"]),
                "class_teacher_subject": (ids["7B"], ids["teacher"], ids["maths"]),
                "teacher_school": (ids["teacher"], ids["school"]),
            }[table]
            placeholders = ", ".join(f":v{i}" for i in range(len(values)))
            with engine.begin() as conn, pytest.raises(sa.exc.IntegrityError):
                conn.execute(
                    sa.text(
                        f"INSERT INTO {table} ({columns}, valid_from, valid_to)"
                        f" VALUES ({placeholders}, now(), '2027-01-01', NULL)"
                    ),
                    {f"v{i}": v for i, v in enumerate(values)},
                )
        finally:
            engine.dispose()


def test_a_pupil_who_left_in_february_can_rejoin_in_may(db_url: str) -> None:
    """The case the widened key was widened FOR.

    One closed row and one open row for the same pair is legal and has to be:
    Lea leaves niveau 2 in February and comes back in May, and both facts have
    to be on the record. This is the other half of the index's meaning — it
    constrains *open* rows, not rows.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0026")
            with engine.begin() as conn:
                ids = _seed_at_0026(conn)
            command.upgrade(cfg, "0027")

            with engine.begin() as conn:
                # Leaving is an UPDATE, never a DELETE (D87).
                conn.execute(
                    sa.text(
                        "UPDATE class_student SET valid_to = '2027-02-15'"
                        " WHERE class_id = :c AND student_id = :s"
                    ),
                    {"c": ids["7B"], "s": ids["lea"]},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO class_student"
                        " (class_id, student_id, enrolled_at, valid_from, valid_to)"
                        " VALUES (:c, :s, now(), '2027-05-01', NULL)"
                    ),
                    {"c": ids["7B"], "s": ids["lea"]},
                )

            with engine.connect() as conn:
                rows = conn.execute(
                    sa.text(
                        "SELECT valid_from, valid_to FROM class_student"
                        " WHERE class_id = :c AND student_id = :s ORDER BY valid_from"
                    ),
                    {"c": ids["7B"], "s": ids["lea"]},
                ).all()
            assert len(rows) == 2, "the gap-then-return could not be represented"
            assert rows[0][1] == date(2027, 2, 15)
            assert rows[1][1] is None
        finally:
            engine.dispose()


# --- The downgrade is lossy exactly where it says it is ---------------------


def test_the_downgrade_drops_ended_memberships_and_keeps_open_ones(db_url: str) -> None:
    """A pupil who left must not reappear on the roster.

    Going back to a schema with no way to say "ended", the only two honest
    options are to drop the ended rows or to refuse to downgrade. Keeping them
    would silently re-enrol a child in a class they left, which is the one
    outcome the migration exists to prevent.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0026")
            with engine.begin() as conn:
                ids = _seed_at_0026(conn)
            command.upgrade(cfg, "0027")

            with engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "UPDATE class_student SET valid_to = '2027-02-15'"
                        " WHERE student_id = :s"
                    ),
                    {"s": ids["noah"]},
                )

            command.downgrade(cfg, "0026")

            with engine.connect() as conn:
                remaining = _roster(conn, ids["7B"], open_only=False)
            assert ids["noah"] not in remaining, "a pupil who left came back"
            assert remaining == {ids["lea"], ids["evening"]}
        finally:
            engine.dispose()
