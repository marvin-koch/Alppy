"""Reconstructing the agenda for work that happened before the log existed.

Kept apart from `test_timeline.py` because it tests a different thing: not what
the agenda shows, but whether history can be recovered honestly — and, just as
importantly, which parts of it must NOT be invented.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, make_exercise, make_paper_trail

from alppy.models import Event
from alppy.models.enums import EventKind
from alppy.services.event_backfill import backfill_events

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def test_the_backfill_reconstructs_history_and_repeats_harmlessly(
    db: Session, tenant: Tenant
) -> None:
    """An empty agenda on an existing database says nothing ever happened.

    The reconstruction reads only real timestamps, and running it twice must add
    nothing — it is wired into a container entrypoint, so it runs on every start.
    """
    exercise = make_exercise(db, tenant, statement="Combien font 2 + 3 ?")
    make_paper_trail(db, tenant, exercise, tenant.students[0])
    db.commit()

    first = backfill_events(db)
    db.commit()
    assert first.total > 0, "there is real history here to reconstruct"
    assert first.sheets >= 1
    assert first.scans >= 1

    after_first = db.query(Event).count()
    second = backfill_events(db)
    db.commit()
    assert second.total == 0, "a second run must add nothing"
    assert db.query(Event).count() == after_first


def test_the_backfill_never_invents_a_print(db: Session, tenant: Tenant) -> None:
    """`SHEET_PRINTED` had no timestamp before this feature — that absence is
    half the reason the log exists.

    Deriving one from `rendered_at` would put a fact in the agenda that nobody
    observed, and a teacher cannot tell an inferred line from an evidenced one.
    A gap is the honest answer.
    """
    exercise = make_exercise(db, tenant, statement="Combien font 4 + 4 ?")
    sheet, _scan, _detection = make_paper_trail(db, tenant, exercise, tenant.students[0])
    sheet.rendered_at = NOW
    db.commit()

    backfill_events(db)
    db.commit()

    assert db.query(Event).filter(Event.kind == EventKind.SHEET_RENDERED).count() == 1
    assert db.query(Event).filter(Event.kind == EventKind.SHEET_PRINTED).count() == 0
