"""0028 splits the pupil from the year. The backfill has to be exact.

The second of the two Critical fixes from the first audit, and the one with the
worst failure mode in the product: ``attempt.student_id`` is renamed to
``person_id`` **and rewritten** through a mapping created in the same
migration. If that rewrite attaches a row to the wrong person, a child's whole
history moves onto another child — and every existing test stays green, because
the unit suite builds a schema where ``attempt`` has always hung off
``person_id`` and the relationship is already correct from scratch. There is no
shape to notice. ``check-schema-drift.py`` sees a perfect schema either way.

What this module pins, in the migration's own words:

* **"Exactly one ``person`` per existing ``student``, created from that
  student's own names and timestamps. The mapping is total and injective."**
  Total and injective is exactly what makes the rewrite safe, so it is
  asserted as a property of the whole table rather than sampled.
* **"The new ids are deliberately fresh, not copied from ``student.id``."**
  Reusing the uuid would make every place that confuses the two id spaces keep
  working until the first pupil had two ``student`` rows. Freshness is what
  turns that confusion into a foreign key violation on the day it is written,
  so it is a behaviour and it is tested.
* **"The print and scan path does not move."** ``scan_page.student_id`` stays
  on the year-bound row, because a UID is a fact about one year's paper.
* **Nothing merges two years by itself.** A pupil repeating a year has two
  ``student`` rows and becomes *two* persons: no uid, name or class joins them,
  and the migration does not guess. That is the honest behaviour and pinning it
  is what stops someone "improving" it into a name-matching heuristic later.

The seed is two school years on purpose. One year cannot tell a correct
rewrite from an accidental one: with a single year, mapping every attempt to
*any* person of the right school would pass.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

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

require_or_skip("migration 0028")

pytestmark = pytest.mark.skipif(SERVER_URL is None, reason=SKIP_REASON)


@pytest.fixture
def db_url() -> Iterator[str]:
    yield from disposable_database()


#: (key, uid, number, first, last, year key) — four enrolment records, three
#: humans. "lea_b" is Lea again, a year later, in a different class.
_STUDENTS = [
    ("lea_a", "7B_01", 1, "Lea", "Roth", "year_a", "class_a"),
    ("noah_a", "7B_02", 2, "Noah", "Berger", "year_a", "class_a"),
    ("lea_b", "8B_01", 1, "Lea", "Roth", "year_b", "class_b"),
    ("mia_b", "8B_02", 2, "Mia", "Keller", "year_b", "class_b"),
]

#: (attempt key, student key, exercise key, sheet key, correct). Five attempts
#: over two years, and both of Lea's years are represented — the case a
#: single-year seed cannot test.
#:
#: Two exercises and two sheets because `uq_attempt_student_exercise_sheet`
#: allows one attempt per (student, exercise, sheet): the anti-double-count
#: backstop this migration renames rather than changes.
_ATTEMPTS = [
    ("a1", "lea_a", "exercise", "sheet_a", True),
    ("a2", "lea_a", "exercise2", "sheet_a", False),
    ("a3", "noah_a", "exercise", "sheet_a", True),
    ("a4", "lea_b", "exercise", "sheet_b", False),
    ("a5", "mia_b", "exercise2", "sheet_b", True),
]


def _seed_at_0027(conn: sa.Connection) -> dict[str, uuid.UUID]:
    """A world in the OLD shape: evidence hanging off the year-bound row."""
    keys = [
        "school", "year_a", "year_b", "teacher", "maths", "class_a", "class_b",
        "exercise", "exercise2", "chapter", "sheet_a", "sheet_b", "scan", "page",
    ]
    ids = {k: uuid.uuid4() for k in keys}
    ids |= {k: uuid.uuid4() for k, *_ in _STUDENTS}
    ids |= {k: uuid.uuid4() for k, *_ in _ATTEMPTS}

    conn.execute(
        sa.text(
            "INSERT INTO school (id, name, canton, default_curriculum, created_at, updated_at)"
            " VALUES (:i, 'CO de Sion', 'VS', 'PER', now(), now())"
        ),
        {"i": ids["school"]},
    )
    for key, label, starts, ends, current in (
        ("year_a", "2026/27", "2026-08-01", "2027-07-31", False),
        ("year_b", "2027/28", "2027-08-01", "2028-07-31", True),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO school_year (id, school_id, label, starts_on, ends_on,"
                " is_current, created_at, updated_at)"
                " VALUES (:i, :s, :l, :f, :t, :c, now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "l": label,
                "f": starts, "t": ends, "c": current,
            },
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
    for key, year_key, code in (("class_a", "year_a", "7B"), ("class_b", "year_b", "8B")):
        conn.execute(
            sa.text(
                "INSERT INTO class (id, school_id, school_year_id, head_teacher_id, code,"
                " kind, created_at, updated_at)"
                " VALUES (:i, :s, :y, :t, :c, 'homeroom', now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "y": ids[year_key],
                "t": ids["teacher"], "c": code,
            },
        )
    for key, uid, number, first, last, year_key, class_key in _STUDENTS:
        conn.execute(
            sa.text(
                "INSERT INTO student (id, school_id, home_class_id, school_year_id, uid,"
                " number, first_name, last_name, created_at, updated_at)"
                " VALUES (:i, :s, :c, :y, :u, :n, :f, :l, now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "c": ids[class_key],
                "y": ids[year_key], "u": uid, "n": number, "f": first, "l": last,
            },
        )
    conn.execute(
        sa.text(
            "INSERT INTO chapter (id, school_id, subject_id, key, labels, position,"
            " created_at, updated_at)"
            " VALUES (:i, :s, :b, 'unfiled', '{\"fr\": \"Sans theme\"}'::jsonb, 0, now(), now())"
        ),
        {"i": ids["chapter"], "s": ids["school"], "b": ids["maths"]},
    )
    for key, statement in (
        ("exercise", "2/3 + 1/3 ?"),
        ("exercise2", "5/6 - 1/6 ?"),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO exercise (id, school_id, subject_id, type, origin, language,"
                " statement, difficulty, created_at, updated_at)"
                " VALUES (:i, :s, :b, 'MCQ', 'TEXTBOOK', 'fr', :q, 2, now(), now())"
            ),
            {"i": ids[key], "s": ids["school"], "b": ids["maths"], "q": statement},
        )
    # One sheet per year: a sheet belongs to one class in one school year, which
    # is the fact that makes per-person and per-student uniqueness select the
    # same rows after the rename.
    for key, class_key, title in (
        ("sheet_a", "class_a", "Fractions, 7B"),
        ("sheet_b", "class_b", "Fractions, 8B"),
    ):
        conn.execute(
            sa.text(
                "INSERT INTO sheet (id, school_id, class_id, subject_id, chapter_id, title,"
                " target, language, layout_version, created_at, updated_at)"
                " VALUES (:i, :s, :c, :b, :ch, :t, 'CLASS', 'fr', 'v1', now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "c": ids[class_key],
                "b": ids["maths"], "ch": ids["chapter"], "t": title,
            },
        )
    for key, student_key, exercise_key, sheet_key, correct in _ATTEMPTS:
        conn.execute(
            sa.text(
                "INSERT INTO attempt (id, school_id, student_id, exercise_id, sheet_id,"
                " correct, score, difficulty, answered_at, created_at, updated_at)"
                " VALUES (:i, :s, :st, :e, :sh, :c, 1.0, 2, now(), now(), now())"
            ),
            {
                "i": ids[key], "s": ids["school"], "st": ids[student_key],
                "e": ids[exercise_key], "sh": ids[sheet_key], "c": correct,
            },
        )

    # The print and scan path, which must NOT follow the person.
    conn.execute(
        sa.text(
            "INSERT INTO scan (id, school_id, sheet_id, original_filename, storage_key,"
            " status, created_at, updated_at)"
            " VALUES (:i, :s, :sh, 'copies.pdf', 'scans/copies.pdf', 'CONFIRMED', now(), now())"
        ),
        {"i": ids["scan"], "s": ids["school"], "sh": ids["sheet_a"]},
    )
    conn.execute(
        sa.text(
            "INSERT INTO scan_page (id, school_id, scan_id, page_index, image_key,"
            " registered, student_id, created_at, updated_at)"
            " VALUES (:i, :s, :sc, 0, 'scans/page-000.png', true, :st, now(), now())"
        ),
        {
            "i": ids["page"], "s": ids["school"], "sc": ids["scan"],
            "st": ids["lea_a"],
        },
    )
    return ids


def _attempts_by(conn: sa.Connection, column: str) -> dict[uuid.UUID, uuid.UUID]:
    return dict(conn.execute(sa.text(f"SELECT id, {column} FROM attempt")).all())


def _student_to_person(conn: sa.Connection) -> dict[uuid.UUID, uuid.UUID]:
    return dict(conn.execute(sa.text("SELECT id, person_id FROM student")).all())


# --- The test the whole module exists for -----------------------------------


def test_every_attempt_follows_its_own_pupil_across_two_school_years(db_url: str) -> None:
    """The rewrite is exact, per row, and not merely plausible.

    Checked as a composition rather than by spot-check: for every attempt, the
    person it points at afterwards must be the person of precisely the student
    it pointed at before. A rewrite that attached Lea's October evidence to
    Noah satisfies "every attempt has a person" and fails this.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                ids = _seed_at_0027(conn)
                before = _attempts_by(conn, "student_id")
            assert len(before) == len(_ATTEMPTS)

            command.upgrade(cfg, "0028")

            with engine.connect() as conn:
                after = _attempts_by(conn, "person_id")
                mapping = _student_to_person(conn)

            assert set(after) == set(before), "an attempt was lost or invented"
            for attempt_id, student_id in before.items():
                assert after[attempt_id] == mapping[student_id], (
                    f"attempt {attempt_id} moved to the wrong person: it belonged "
                    f"to student {student_id}"
                )
            # And name the consequence explicitly, so a failure reads as what it
            # would mean rather than as a uuid mismatch.
            assert after[ids["a1"]] == mapping[ids["lea_a"]]
            assert after[ids["a4"]] == mapping[ids["lea_b"]]
            assert after[ids["a3"]] == mapping[ids["noah_a"]]
        finally:
            engine.dispose()


def test_the_mapping_is_total_and_injective(db_url: str) -> None:
    """Exactly one person per student row — the property the rewrite rests on.

    Not injective and two pupils share a history. Not total and a student row
    has no identity, which is a NOT NULL violation the migration would have
    hit — but only if every row was reached, which is the half this asserts.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                _seed_at_0027(conn)
            command.upgrade(cfg, "0028")

            with engine.connect() as conn:
                students = conn.execute(sa.text("SELECT count(*) FROM student")).scalar_one()
                people = conn.execute(sa.text("SELECT count(*) FROM person")).scalar_one()
                distinct = conn.execute(
                    sa.text("SELECT count(DISTINCT person_id) FROM student")
                ).scalar_one()
                orphans = conn.execute(
                    sa.text("SELECT count(*) FROM student WHERE person_id IS NULL")
                ).scalar_one()
            assert students == len(_STUDENTS)
            assert people == students, "not one person per student row"
            assert distinct == students, "two student rows share a person"
            assert orphans == 0
        finally:
            engine.dispose()


def test_a_pupil_repeating_a_year_is_not_silently_merged(db_url: str) -> None:
    """Lea has two enrolment records and becomes two persons.

    This is the documented behaviour, not a defect: nothing joins the two rows
    — not the uid (it changes with the class), not the name (homonyms, spelling,
    a roster pasted differently) — and a migration that guessed would merge two
    different children who happen to share a name. Pinning it is what stops the
    guess being added later as an improvement.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                ids = _seed_at_0027(conn)
            command.upgrade(cfg, "0028")

            with engine.connect() as conn:
                mapping = _student_to_person(conn)
                names = dict(
                    conn.execute(
                        sa.text("SELECT id, first_name || ' ' || last_name FROM person")
                    ).all()
                )
            assert mapping[ids["lea_a"]] != mapping[ids["lea_b"]]
            # Both carry her name, copied from the student row they were built
            # from — so the two are findable, just not joined.
            assert names[mapping[ids["lea_a"]]] == "Lea Roth"
            assert names[mapping[ids["lea_b"]]] == "Lea Roth"
        finally:
            engine.dispose()


def test_a_person_id_is_never_a_student_id(db_url: str) -> None:
    """Fresh uuids are what make confusing the two id spaces an error.

    Copying ``student.id`` would have made the migration free and every
    ``person_id``/``student_id`` mix-up resolve silently and correctly — until
    the first pupil had two ``student`` rows, by which time the wrong code is
    everywhere. The two id spaces are disjoint on purpose (D87).
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                _seed_at_0027(conn)
            command.upgrade(cfg, "0028")

            with engine.connect() as conn:
                overlap = conn.execute(
                    sa.text("SELECT count(*) FROM person p JOIN student s ON s.id = p.id")
                ).scalar_one()
            assert overlap == 0, "a person reused a student's uuid"
        finally:
            engine.dispose()


def test_the_print_and_scan_path_stays_on_the_year_bound_row(db_url: str) -> None:
    """A UID is a fact about one year's paper, so the pile does not follow.

    ``scan_page.student_id`` still names a ``student``. If it had been swept
    along with the longitudinal tables, a page of last year's copies would
    resolve to a pupil's current enrolment and the uid printed on the paper
    would stop meaning what it says.
    """
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                ids = _seed_at_0027(conn)
            command.upgrade(cfg, "0028")

            with engine.connect() as conn:
                still_there = conn.execute(
                    sa.text("SELECT student_id FROM scan_page WHERE id = :i"),
                    {"i": ids["page"]},
                ).scalar_one()
                assert still_there == ids["lea_a"]
                # And it really is a student, not a person wearing the name.
                is_student = conn.execute(
                    sa.text("SELECT count(*) FROM student WHERE id = :i"),
                    {"i": still_there},
                ).scalar_one()
                assert is_student == 1
        finally:
            engine.dispose()


def test_the_downgrade_puts_every_attempt_back_on_its_student(db_url: str) -> None:
    """Reversible, because the mapping it reverses through is injective."""
    engine = sa.create_engine(db_url)
    with alembic_at(db_url) as cfg:
        try:
            command.upgrade(cfg, "0027")
            with engine.begin() as conn:
                _seed_at_0027(conn)
                before = _attempts_by(conn, "student_id")

            command.upgrade(cfg, "0028")
            command.downgrade(cfg, "0027")

            with engine.connect() as conn:
                after = _attempts_by(conn, "student_id")
            assert after == before, "the round trip moved a pupil's evidence"
        finally:
            engine.dispose()
