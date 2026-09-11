"""The product at the size a real school uses it (T18, T23).

Every fixture in the suite is small — 18 pupils in two classes, a three-page
scan — and small is where N+1 hides. A read that costs one query per pupil is
indistinguishable from a good one at eighteen pupils and is a timeout at a
hundred and forty-four, which is six niveau groups of twenty-four: an ordinary
Cycle 3 maths teacher's whole load.

**Counted queries rather than measured seconds.** A wall-clock budget on a CI
runner is a coin toss — a shared runner under load fails it for reasons that
have nothing to do with the code, and the usual response is to raise the number
until it never fails, at which point it measures nothing. A query count is
deterministic, it is the thing that actually degrades, and when it fails it
names the cause instead of the symptom.

So the claim these tests make is not "this is fast". It is "the cost of this
read does not grow with the number of children in it", which is the property
that makes it fast and the one a refactor silently breaks.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise, seat_students

from alppy.db.validity import today
from alppy.models import (
    Class,
    SchoolYear,
    class_subject,
    class_teacher_subject,
)
from alppy.models.enums import ClassKind
from alppy.services import class_service, mastery_service


class QueryCounter:
    """Every SQL statement this block issued.

    Attached to the Engine rather than the Session so that a lazy load — the
    usual shape of an N+1 — is counted too. Those are precisely the queries
    nobody wrote and nobody sees.
    """

    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)

    def summary(self, limit: int = 5) -> str:
        from collections import Counter

        shapes = Counter(s.split("\n")[0][:90] for s in self.statements)
        lines = [f"      {n:>4}x  {shape}" for shape, n in shapes.most_common(limit)]
        return "\n".join(lines)


@pytest.fixture
def count_queries(db: Session) -> Iterator[QueryCounter]:
    counter = QueryCounter()

    def before(_conn, _cursor, statement, _params, _context, _many) -> None:  # noqa: ANN001
        counter.statements.append(statement)

    engine = db.get_bind()
    sa.event.listen(engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        sa.event.remove(engine, "before_cursor_execute", before)


def _niveau_groups(db: Session, tenant: Tenant, *, groups: int, per_group: int) -> list[Class]:
    """Six groups of twenty-four, the way Cycle 3 actually streams maths.

    Separate classes rather than one large one, because that is the shape that
    produces the load: a teacher holds several groups and the dashboard reads
    all of them.
    """
    year = db.execute(
        sa.select(SchoolYear).where(SchoolYear.school_id == tenant.school.id)
    ).scalars().first()
    assert year is not None

    built: list[Class] = []
    for index in range(groups):
        klass = Class(
            id=uuid.uuid4(),
            school_id=tenant.school.id,
            school_year_id=year.id,
            head_teacher_id=tenant.teacher.id,
            # Unique per call, not merely per loop: `uq_class_code` is per school
            # and school year, so a test that builds two sets collides on the
            # second — which reads as a product failure and is a fixture one.
            code=f"MA-{uuid.uuid4().hex[:6]}-{index + 1}",
            kind=ClassKind.COURSE,
        )
        db.add(klass)
        db.flush()
        seat_students(
            db,
            school_id=tenant.school.id,
            school_year_id=year.id,
            school_class=klass,
            names=[(f"Eleve{n:02d}", f"Groupe{index}") for n in range(1, per_group + 1)],
        )
        # Declare the branch and assign the teacher to it. Reading a pile is
        # PAIR-grained since D73 — a sheet belongs to a (class, subject) — so a
        # head teacher with no assignment gets "scan not found" rather than the
        # volume behaviour under test.
        db.execute(
            class_subject.insert().values(
                class_id=klass.id, subject_id=tenant.subject.id, position=0
            )
        )
        db.execute(
            class_teacher_subject.insert().values(
                class_id=klass.id,
                teacher_id=tenant.teacher.id,
                subject_id=tenant.subject.id,
                valid_from=today(),
            )
        )
        built.append(klass)
    db.commit()
    return built


def test_a_full_teaching_load_is_built(db: Session, tenant: Tenant) -> None:
    """The fixture itself, asserted — 144 children across six groups.

    A volume test whose fixture quietly built six pupils would pass every
    budget below and mean nothing.
    """
    groups = _niveau_groups(db, tenant, groups=6, per_group=24)
    assert len(groups) == 6
    for klass in groups:
        assert len(class_service.list_students(db, tenant.scope, klass.id)) == 24


def test_the_matrix_does_not_cost_a_query_per_pupil(
    db: Session, tenant: Tenant, count_queries: QueryCounter
) -> None:
    """The one that matters. `class_matrix` is the screen a teacher opens first.

    Twenty-four pupils against a handful of competencies is a grid; a query per
    cell is 24 x N round trips for one page view, and on SQLite in a test that
    is merely slow. Against Postgres over a network it is the screen not
    loading.

    The ceiling is deliberately generous — this is not a budget to tune, it is a
    tripwire for growth that is proportional to the roster.
    """
    groups = _niveau_groups(db, tenant, groups=1, per_group=24)
    before = count_queries.count

    matrix = mastery_service.class_matrix(db, tenant.scope, groups[0].id)

    issued = count_queries.count - before
    assert len(matrix.students) == 24
    assert issued < 24, (
        f"the matrix issued {issued} queries for 24 pupils — at least one per "
        f"pupil, which is the shape of an N+1:\n{count_queries.summary()}"
    )


def test_the_matrix_costs_the_same_for_a_class_six_times_the_size(
    db: Session, tenant: Tenant, count_queries: QueryCounter
) -> None:
    """Constant, not merely small.

    A read can be under the ceiling above and still be linear — twenty queries
    for twenty-four pupils passes, and is a hundred and twenty for a hundred and
    forty-four. Comparing two sizes is what tells those apart, and it is the
    assertion a refactor has to keep true.
    """
    small = _niveau_groups(db, tenant, groups=1, per_group=4)[0]
    large = _niveau_groups(db, tenant, groups=1, per_group=24)[0]

    start = count_queries.count
    mastery_service.class_matrix(db, tenant.scope, small.id)
    for_four = count_queries.count - start

    start = count_queries.count
    mastery_service.class_matrix(db, tenant.scope, large.id)
    for_twenty_four = count_queries.count - start

    assert for_twenty_four <= for_four + 2, (
        f"the matrix cost {for_four} queries for 4 pupils and {for_twenty_four} "
        f"for 24: the cost grows with the roster.\n{count_queries.summary()}"
    )


def test_a_roster_read_does_not_grow_with_the_roster(
    db: Session, tenant: Tenant, count_queries: QueryCounter
) -> None:
    """`list_students` is called on nearly every class-scoped screen."""
    small = _niveau_groups(db, tenant, groups=1, per_group=4)[0]
    large = _niveau_groups(db, tenant, groups=1, per_group=24)[0]

    start = count_queries.count
    class_service.list_students(db, tenant.scope, small.id)
    for_four = count_queries.count - start

    start = count_queries.count
    class_service.list_students(db, tenant.scope, large.id)
    for_twenty_four = count_queries.count - start

    assert for_twenty_four <= for_four + 2, (
        f"{for_four} queries for 4 pupils, {for_twenty_four} for 24\n"
        f"{count_queries.summary()}"
    )


def test_a_teachers_whole_load_is_one_dashboard_read(
    db: Session, tenant: Tenant, count_queries: QueryCounter
) -> None:
    """Six groups on the home screen must not be six times the work.

    `class_out_with_counts` is what fills the dashboard cards, and a roster
    count fetched per class is the classic version of this bug — invisible at
    the two classes every fixture has.
    """
    groups = _niveau_groups(db, tenant, groups=6, per_group=24)

    start = count_queries.count
    for klass in groups:
        class_service.class_out_with_counts(db, tenant.scope, klass)
    issued = count_queries.count - start

    assert issued <= 6 * 4, (
        f"{issued} queries to summarise 6 classes — more than four each:\n"
        f"{count_queries.summary()}"
    )


def test_a_thirty_page_pile_grades_every_page(db: Session, tenant: Tenant) -> None:
    """The other axis: a class set photographed one copy at a time.

    Every E2E fixture uses three pages. Thirty is what a teacher actually
    carries back from a lesson, and it is the number at which "one query per
    page, per item" stops being free.
    """
    from alppy.models import Detection, Scan, ScanPage, Sheet, SheetItem
    from alppy.models.enums import DetectionOutcome, ScanStatus, SheetTarget

    year = db.execute(
        sa.select(SchoolYear).where(SchoolYear.school_id == tenant.school.id)
    ).scalars().first()
    assert year is not None
    klass = _niveau_groups(db, tenant, groups=1, per_group=30)[0]
    pupils = class_service.list_students(db, tenant.scope, klass.id)
    assert len(pupils) == 30

    exercise = make_exercise(db, tenant, statement="2/3 + 1/3 ?")
    sheet = Sheet(
        id=uuid.uuid4(), school_id=tenant.school.id, class_id=klass.id,
        subject_id=tenant.subject.id, chapter_id=tenant.unfiled_chapter_id,
        title="Fractions", target=SheetTarget.CLASS, language="fr",
        layout_version="v1",
    )
    db.add(sheet)
    db.flush()
    db.add(
        SheetItem(
            id=uuid.uuid4(), school_id=tenant.school.id, sheet_id=sheet.id,
            exercise_id=exercise.id, position=0,
        )
    )
    scan = Scan(
        id=uuid.uuid4(), school_id=tenant.school.id, sheet_id=sheet.id,
        original_filename="copies.pdf", storage_key="scans/copies.pdf",
        status=ScanStatus.NEEDS_REVIEW,
    )
    db.add(scan)
    db.flush()
    for index, pupil in enumerate(pupils):
        page = ScanPage(
            id=uuid.uuid4(), school_id=tenant.school.id, scan_id=scan.id,
            page_index=index, image_key=f"scans/page-{index:03d}.png",
            registered=True, student_id=pupil.id,
        )
        db.add(page)
        db.flush()
        db.add(
            Detection(
                id=uuid.uuid4(), school_id=tenant.school.id, scan_page_id=page.id,
                exercise_id=exercise.id, item_index=0, detected_index=0,
                confidence=0.97, outcome=DetectionOutcome.DETECTED,
            )
        )
    db.commit()

    result = scan_confirm(db, tenant, scan.id)

    assert result.attempts_created == 30, (
        f"30 pages, {result.attempts_created} attempts — a page was dropped"
    )


def scan_confirm(db: Session, tenant: Tenant, scan_id: uuid.UUID):  # noqa: ANN201
    from alppy.services import scan_service

    return scan_service.confirm_scan(db, tenant.scope, scan_id)
