"""Two fixes that shipped with nothing to stop them coming back (T21).

A `fix:` commit with no test is a fix with a half-life. Both of these were found
the expensive way — one by a week of intermittent red builds, the other by a
`NameError` reaching a branch — and both were repaired by editing a single line,
which is exactly the kind of line a later refactor undoes without noticing.

Neither test is about the code that was changed. They are about the SYMPTOM,
because the symptom is what a future reader will recognise.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login, make_exercise

from alppy.models import Competency, MasteryBranchSnapshot, MasterySnapshot
from alppy.models.enums import MasteryBand

# --- 7658dd5 · the bulk snapshot write that flaked one run in three ---------


def _competency(db: Session, tenant: Tenant, code: str) -> Competency:
    row = Competency(
        id=uuid.uuid4(),
        # The edition the fixture's own competency belongs to. A curriculum is
        # published in editions now, and a competency without one is not a
        # competency — inventing a fresh edition here would put these rows in a
        # curriculum nothing else references.
        edition_id=tenant.competency.edition_id,
        curriculum="PER",
        code=code,
        subject_key="mathematics",
        cycle=3,
        labels={"fr": code},
        description="",
    )
    db.add(row)
    db.flush()
    return row


@pytest.mark.parametrize("rows", [2, 8, 25])
def test_writing_many_snapshots_at_once_does_not_ask_for_returning(
    db: Session, tenant: Tenant, rows: int
) -> None:
    """The flake, reproduced as a rule instead of as a probability.

    Roughly one full-suite run in three failed with `AttributeError: 'float'
    object has no attribute 'replace'`, on a different test each time, which is
    why it read as flakiness rather than as a bug. `TimestampMixin` puts a
    `server_default` on every table and SQLAlchemy fetches server defaults back
    eagerly, so a bulk insert compiled to `... RETURNING created_at, updated_at,
    id` and handed the result to the `insertmanyvalues` machinery. Postgres
    declares a sentinel and correlates the rows for free; SQLite does not, so
    SQLAlchemy keys on a sentinel column and sometimes applied the UUID
    processor to a timestamp.

    `eager_defaults=False` on the two snapshot mappers removes the RETURNING, so
    the path cannot be reached. Asserting the mapper setting rather than looping
    the insert a hundred times is the difference between a test that fails
    always and one that fails one run in three — which is the bug over again.
    """
    competencies = [_competency(db, tenant, f"MSN {30 + n}") for n in range(rows)]
    person_id = tenant.students[0].person_id

    db.add_all(
        [
            MasterySnapshot(
                id=uuid.uuid4(),
                school_id=tenant.school.id,
                person_id=person_id,
                competency_id=competency.id,
                computed_at=datetime.now(UTC),
                score=0.75,
                band=MasteryBand.OK,
            )
            for competency in competencies
        ]
    )
    db.flush()

    written = (
        db.query(MasterySnapshot).filter(MasterySnapshot.person_id == person_id).count()
    )
    assert written == rows


@pytest.mark.parametrize("mapper", [MasterySnapshot, MasteryBranchSnapshot])
def test_the_snapshot_mappers_do_not_fetch_their_defaults_eagerly(mapper: type) -> None:
    """The setting itself, because the setting IS the fix.

    These two tables are written in bulk after every confirmed scan and their
    timestamps are never read back in the same transaction — there was nothing
    to fetch eagerly, which is why this is the right setting on its own terms
    and not only as a way out of a SQLAlchemy corner.

    A future `TimestampMixin` change, or a mapper rewrite, puts it back without
    anyone connecting it to a `'float' object has no attribute 'replace'` a
    fortnight later.
    """
    from sqlalchemy import inspect

    assert inspect(mapper).eager_defaults is False, (
        f"{mapper.__name__} fetches its server defaults eagerly again. A bulk "
        f"write of this table compiles to INSERT ... RETURNING, which on SQLite "
        f"goes through insertmanyvalues and intermittently applies the wrong "
        f"type processor — one full-suite run in three, on a different test each "
        f"time. See 7658dd5."
    )


# --- bf0e495 · a gate that did not exist ------------------------------------


def test_listing_feedback_calls_a_gate_that_exists(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    """`list_feedback` called `sheet_svc.get_sheet_for_read`, which does not exist.

    A `NameError`-class defect: the tenancy check was written, reviewed and
    wrong, and the route answered 500 for everyone rather than 404 for a
    stranger. It reached the branch because no test issued the request — the
    same gap the route sweep now closes wholesale, asserted here as the specific
    behaviour so a failure names this bug rather than "some route 500s".
    """
    login(client, tenant.teacher.email)

    mine = client.get(
        "/api/v1/adaptive/feedback",
        params={"source_sheet_id": str(uuid.uuid4())},
    )
    assert mine.status_code != 500, mine.text
    assert mine.status_code == 404, mine.text


def test_another_schools_sheet_reads_as_missing_from_the_feedback_list(
    client: TestClient, tenant: Tenant, other_tenant: Tenant, db: Session
) -> None:
    """And the gate does what it was there to do, now that it runs.

    A 500 is not a tenancy failure — nothing leaked — but it is a check that was
    not running, and the difference only showed once it did.
    """
    from alppy.models import Sheet
    from alppy.models.enums import SheetTarget

    foreign = Sheet(
        id=uuid.uuid4(),
        school_id=other_tenant.school.id,
        class_id=other_tenant.school_class.id,
        subject_id=other_tenant.subject.id,
        chapter_id=other_tenant.unfiled_chapter_id,
        title="Fractions",
        target=SheetTarget.CLASS,
        language="fr",
        layout_version="v1",
    )
    db.add(foreign)
    db.flush()
    db.commit()
    make_exercise(db, other_tenant, statement="3/4 - 1/4 ?")

    login(client, tenant.teacher.email)
    response = client.get(
        "/api/v1/adaptive/feedback", params={"source_sheet_id": str(foreign.id)}
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"
