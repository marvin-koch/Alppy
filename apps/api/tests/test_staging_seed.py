"""Staging holds no real child, and can be checked to hold none.

The rule is easy to state and hard to keep: no real student data outside
production. What makes it keepable is that staging's roster comes from a
**closed corpus** (`alppy.seed.staging`), so "is this row synthetic" has an
answer a script can compute — and this file is that script, run in CI against
the generator, plus the guards that stop staging being seeded by accident or
seeded with the passwords published in this repository.

The guard against real data is deliberately a property of the *data*, not of a
process. A rule that depends on nobody ever running an import against staging is
not a rule; a query that fails when a name outside the corpus appears is.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, seat_students

from alppy.core.config import Settings
from alppy.models import Student
from alppy.seed import staging


# --------------------------------------------------------------------------
# The corpus
# --------------------------------------------------------------------------
def test_the_dataset_is_large_enough_to_be_worth_testing_on() -> None:
    """A class of five tells you nothing about a class list that scrolls or a
    batch render that takes a minute. Six taught classes of twenty is the point
    of having a staging dataset at all."""
    taught = [c for c in staging.STAGING_CLASSES if c.taught]
    assert len(taught) == 6
    assert all(c.size == 20 for c in taught)
    assert staging.total_students() >= 120


def test_both_curricula_are_represented() -> None:
    """A single-canton dataset never exercises D56 — the same chapter filed
    under each canton's own code — which is the case most likely to break and
    the least likely to be noticed."""
    kinds = {kind for _canton, kind in staging.STAGING_SCHOOLS.values()}
    assert kinds == {staging.CurriculumKind.PER, staging.CurriculumKind.LP21}
    schools = {c.school for c in staging.STAGING_CLASSES}
    assert schools == set(staging.STAGING_SCHOOLS)


def test_one_class_has_a_roster_and_no_history() -> None:
    """Every "nothing taught yet" empty state is otherwise unreachable without
    hand-editing the database, and an empty state nobody can reach is one
    nobody has looked at."""
    untaught = [c for c in staging.STAGING_CLASSES if not c.taught]
    assert len(untaught) == 1
    assert untaught[0].size > 0


def test_every_generated_roster_is_inside_the_corpus() -> None:
    """The closed-corpus property, which is what makes the guard below able to
    say anything at all."""
    for entry in staging.STAGING_CLASSES:
        roster = staging.roster_for(entry.code, entry.size)
        assert len(roster) == entry.size
        for first, last in roster:
            assert staging.is_synthetic(first, last), (entry.code, first, last)


def test_the_roster_is_deterministic_across_runs() -> None:
    """A staging rebuild must not renumber the class: a bug report naming
    "9C_14" has to still mean the same student next week."""
    assert staging.roster_for("9C", 20) == staging.roster_for("9C", 20)


def test_two_classes_do_not_share_one_roster() -> None:
    """Identical rosters would hide every cross-class bug — the class filter
    that does nothing looks correct when both classes contain the same people."""
    assert staging.roster_for("7A", 20) != staging.roster_for("7B", 20)


def test_staging_accounts_cannot_reach_a_real_inbox() -> None:
    """`.invalid` is reserved by RFC 2606 and never resolves. A staging deploy
    that sends a reset or an error report must not be able to mail a teacher."""
    assert staging.STAGING_TEACHER_DOMAIN.endswith(".invalid")


def test_the_corpus_carries_no_note_of_a_real_person() -> None:
    """Cheap and worth having: the corpus is hand-written, and the failure mode
    is somebody pasting a real class list into it."""
    assert len(staging.STAGING_GIVEN_NAMES) == len(set(staging.STAGING_GIVEN_NAMES))
    assert len(staging.STAGING_SURNAMES) == len(set(staging.STAGING_SURNAMES))
    assert all(name.strip() == name and name for name in staging.STAGING_NAME_CORPUS)


# --------------------------------------------------------------------------
# The guard itself
# --------------------------------------------------------------------------
def audit_students(db: Session) -> list[Student]:
    """Every student whose name could not have come from the generator.

    This is the check to run against a staging database — as a smoke test after
    a deploy, or on a schedule. It is written here, against the models, so it
    stays in step with them.
    """
    return [
        student
        for student in db.query(Student).all()
        if not staging.is_synthetic(student.first_name, student.last_name)
    ]


def _clear_roster(db: Session) -> None:
    """Empty the roster the `tenant` fixture seats, enrollments included.

    Deleting the students alone would leave `class_student` rows pointing at
    nothing, which the next insert trips over — the same two-facts-per-student
    shape `seat_students` exists for (D69), from the other direction.
    """
    from alppy.models import class_student

    db.execute(class_student.delete())
    db.query(Student).delete()
    db.commit()


def _seat(db: Session, tenant: Tenant, names: list[tuple[str, str]]) -> None:
    """Seat a roster the way the product does — home class and enrollment both
    (D69), so the rows the audit reads are the rows staging would really hold."""
    seat_students(
        db,
        school_id=tenant.school.id,
        school_year_id=tenant.school_class.school_year_id,
        school_class=tenant.school_class,
        names=names,
    )
    db.commit()


def test_a_generated_roster_passes_the_audit(db: Session, tenant: Tenant) -> None:
    _clear_roster(db)  # the fixture seats a roster of its own
    _seat(db, tenant, staging.roster_for("7A", 20))

    assert audit_students(db) == []
    assert db.query(Student).count() == 20


def test_a_name_from_outside_the_corpus_is_caught(db: Session, tenant: Tenant) -> None:
    """The whole point. A real roster imported into staging "just to test with"
    is exactly this shape, and it must not be silent."""
    _clear_roster(db)
    _seat(db, tenant, [("Aloysius", "Featherstonehaugh")])

    flagged = audit_students(db)
    assert [s.last_name for s in flagged] == ["Featherstonehaugh"]


def test_the_audit_catches_a_half_real_name(db: Session, tenant: Tenant) -> None:
    """A real surname with a corpus given name still fails: both halves have to
    come from the corpus, because a surname is the identifying half."""
    _clear_roster(db)
    _seat(db, tenant, [(staging.STAGING_GIVEN_NAMES[0], "Featherstonehaugh")])

    assert [s.last_name for s in audit_students(db)] == ["Featherstonehaugh"]


def test_a_roster_mixing_real_and_synthetic_reports_only_the_real(
    db: Session, tenant: Tenant
) -> None:
    """The realistic shape of the accident: a mostly-synthetic staging database
    with one imported class in it. Reporting "the data is not clean" is useless;
    naming the rows is what lets somebody delete them."""
    _clear_roster(db)
    _seat(
        db,
        tenant,
        [*staging.roster_for("7A", 5), ("Aloysius", "Featherstonehaugh")],
    )

    assert [s.last_name for s in audit_students(db)] == ["Featherstonehaugh"]


# --------------------------------------------------------------------------
# Seeding staging is deliberate, or it does not happen
# --------------------------------------------------------------------------
@pytest.fixture
def _staging_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from alppy import cli

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="staging",
        secret_key="a-real-and-sufficiently-long-secret",
        s3_secret_key="a-real-bucket-password",
        s3_bucket="alppy-staging-scans",
        production_s3_bucket="alppy-scans",
        database_url="postgresql+psycopg://alppy_app:pw@db.internal:5432/alppy",
        admin_database_url="postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
        cors_origins=("https://staging.alppy.ch",),
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    yield


def test_the_entrypoint_seed_refuses_staging(_staging_env: None) -> None:
    """`infra/api/entrypoint.sh` runs `seed` with no arguments on every start of
    the serve role. In staging that must do nothing at all — and exit 0, because
    the entrypoint treats a failed seed as survivable and a scary line in the log
    of a correct deployment is how a check gets ignored."""
    from alppy import cli

    assert cli._seed() == 0


def test_seeding_staging_without_a_password_is_refused(_staging_env: None) -> None:
    """The flag says a human meant it. This says they brought a password: the
    demo constants are published in this repository."""
    from alppy import cli

    assert cli._seed(allow_staging=True) == 1


def test_production_is_never_seedable_even_with_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from alppy import cli

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        env="production",
        secret_key="a-real-and-sufficiently-long-secret",
        s3_secret_key="a-real-bucket-password",
        s3_bucket="alppy-scans",
        production_s3_bucket="alppy-scans-other",
        database_url="postgresql+psycopg://alppy_app:pw@db.internal:5432/alppy",
        admin_database_url="postgresql+psycopg://alppy:pw@db.internal:5432/alppy",
        cors_origins=("https://app.alppy.ch",),
        seed_teacher_password="a-real-password",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli._seed(allow_staging=True) == 0


def test_the_flag_is_not_something_the_entrypoint_passes() -> None:
    """A guard whose bypass is wired into the container start is not a guard."""
    from pathlib import Path

    entrypoint = Path(__file__).resolve().parents[3] / "infra" / "api" / "entrypoint.sh"
    assert "--allow-staging" not in entrypoint.read_text()


def test_staging_and_production_are_the_only_names_that_matter(_staging_env: None) -> None:
    from alppy import cli

    assert frozenset({"local", "ci"}) == cli.SEEDABLE_ENVS
    assert frozenset({"staging"}) == cli.EXPLICITLY_SEEDABLE_ENVS
    # No overlap: an environment cannot be both unattended-seedable and gated.
    assert not (cli.SEEDABLE_ENVS & cli.EXPLICITLY_SEEDABLE_ENVS)


# --------------------------------------------------------------------------
# The generator, actually run
# --------------------------------------------------------------------------
def test_the_staging_seed_builds_the_whole_dataset(db: Session) -> None:
    """An integration test, not a unit one: the real seed against the real
    schema. A corpus that is provably synthetic is worth nothing if the thing
    that loads it does not work — and the demo seed's own per-school "already
    seeded" check was wrong for a school holding more than one taught class,
    which only shows up by running it.
    """
    from alppy.models import Attempt, Class, School
    from alppy.seed import run_staging_seed

    summary = run_staging_seed(db, password="a-staging-only-password")

    assert len(summary["schools"]) == 2
    assert summary["students"] == staging.total_students()

    # Every class arrived, including the untaught one.
    codes = {c.code for c in db.query(Class).all()}
    assert codes == {entry.code for entry in staging.STAGING_CLASSES}

    # Both curricula, which is what makes D56 reachable here at all.
    kinds = {s.default_curriculum for s in db.query(School).all()}
    assert kinds == {staging.CurriculumKind.PER, staging.CurriculumKind.LP21}

    # And the whole roster passes the audit that gives the guarantee its teeth.
    assert audit_students(db) == []
    assert db.query(Attempt).count() > 0


def test_every_taught_class_gets_a_history_of_its_own(db: Session) -> None:
    """The bug the per-school check hid: seed class one, and classes two and
    three are skipped because "this school already has attempts" — staging
    comes up two thirds empty and looks seeded."""
    from alppy.models import Attempt, Class, Student
    from alppy.seed import run_staging_seed

    run_staging_seed(db, password="a-staging-only-password")

    for entry in staging.STAGING_CLASSES:
        school_class = (
            db.query(Class).filter(Class.code == entry.code).one()
        )
        student_ids = [
            s.id
            for s in db.query(Student).filter(Student.home_class_id == school_class.id).all()
        ]
        assert len(student_ids) == entry.size, entry.code
        attempts = (
            db.query(Attempt).filter(Attempt.student_id.in_(student_ids)).count()
        )
        if entry.taught:
            assert attempts > 0, f"{entry.code} was taught but has no history"
        else:
            assert attempts == 0, f"{entry.code} must stay empty"


def test_the_staging_seed_is_idempotent(db: Session) -> None:
    """It is run by hand, but by a human who may well run it twice. A second
    pass must not double every student's evidence and shift the whole matrix."""
    from alppy.models import Attempt, Student
    from alppy.seed import run_staging_seed

    run_staging_seed(db, password="a-staging-only-password")
    students, attempts = db.query(Student).count(), db.query(Attempt).count()

    run_staging_seed(db, password="a-staging-only-password")
    assert db.query(Student).count() == students
    assert db.query(Attempt).count() == attempts


def test_the_seeded_accounts_cannot_be_mailed(db: Session) -> None:
    from alppy.models import Teacher
    from alppy.seed import run_staging_seed

    run_staging_seed(db, password="a-staging-only-password")
    for teacher in db.query(Teacher).all():
        assert teacher.email.endswith(staging.STAGING_TEACHER_DOMAIN)


def test_the_published_demo_password_is_never_used(db: Session) -> None:
    """The flag makes staging seedable; this is what stops it being seeded with
    two logins anyone holding this repository already knows."""
    from alppy.core.security import verify_password
    from alppy.models import Teacher
    from alppy.seed import run_staging_seed
    from alppy.seed.demo import DEMO_TEACHER_PASSWORD

    run_staging_seed(db, password="a-staging-only-password")
    for teacher in db.query(Teacher).all():
        assert not verify_password(teacher.password_hash, DEMO_TEACHER_PASSWORD)
        assert verify_password(teacher.password_hash, "a-staging-only-password")
