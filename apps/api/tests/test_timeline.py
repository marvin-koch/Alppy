"""The agenda: what happened, in order, and only what this teacher may see.

The event log exists because two lifecycle moments had no timestamp at all — a
sheet going to the photocopier and a scan being confirmed — and because
`updated_at` cannot stand in for either: it is overwritten by whatever edit
came next.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import (
    Tenant,
    login,
    make_colleague,
    make_exercise,
)

from alppy.models import Event
from alppy.models.enums import EventKind, EventSubject
from alppy.services import event_service

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _event(
    db: Session,
    tenant: Tenant,
    *,
    kind: EventKind = EventKind.SHEET_CREATED,
    summary: str = "Fractions",
    days_ago: int = 0,
    class_id: uuid.UUID | None = None,
    subject_id: uuid.UUID | None = None,
) -> Event | None:
    return event_service.record(
        db,
        school_id=tenant.school.id,
        kind=kind,
        subject_type=EventSubject.SHEET,
        subject_id=subject_id or uuid.uuid4(),
        summary=summary,
        actor_id=tenant.teacher.id,
        class_id=class_id if class_id is not None else tenant.school_class.id,
        occurred_at=NOW - timedelta(days=days_ago),
    )


# --------------------------------------------------------------------------
# 1 · Order and paging
# --------------------------------------------------------------------------
def test_the_agenda_is_newest_first(client, db: Session, tenant: Tenant, signed_in) -> None:
    _event(db, tenant, summary="oldest", days_ago=10)
    _event(db, tenant, summary="middle", days_ago=5)
    _event(db, tenant, summary="newest", days_ago=1)
    db.commit()

    body = client.get("/api/v1/timeline").json()
    assert [i["title"] for i in body["items"]] == ["newest", "middle", "oldest"]
    assert body["total"] == 3


def test_paging_reports_the_full_total(client, db: Session, tenant: Tenant, signed_in) -> None:
    for i in range(5):
        _event(db, tenant, summary=f"sheet {i}", days_ago=i)
    db.commit()

    body = client.get("/api/v1/timeline", params={"limit": 2, "offset": 0}).json()
    assert len(body["items"]) == 2
    assert body["total"] == 5, "the total is the filtered set, not the page"
    assert body["limit"] == 2


# --------------------------------------------------------------------------
# 2 · Filters and facets agree
# --------------------------------------------------------------------------
def test_a_facet_reports_what_selecting_it_would_give(
    client, db: Session, tenant: Tenant, signed_in
) -> None:
    """The bug this shape prevents: a chip promising a count the page cannot
    deliver, because the facet counted a different filter set."""
    _event(db, tenant, kind=EventKind.SHEET_CREATED, summary="a")
    _event(db, tenant, kind=EventKind.SHEET_CREATED, summary="b")
    _event(db, tenant, kind=EventKind.SCAN_CONFIRMED, summary="c")
    db.commit()

    body = client.get("/api/v1/timeline").json()
    facets = body["facets"]["by_kind"]
    assert facets["sheet_created"] == 2
    assert facets["scan_confirmed"] == 1

    # Selecting the chip returns exactly what it promised.
    filtered = client.get("/api/v1/timeline", params={"kind": "scan_confirmed"}).json()
    assert filtered["total"] == facets["scan_confirmed"]
    assert {i["kind"] for i in filtered["items"]} == {"scan_confirmed"}

    # And the facets do NOT shrink to the selection: the other chip still says
    # what choosing it would give.
    assert filtered["facets"]["by_kind"]["sheet_created"] == 2


def test_search_matches_the_summary(client, db: Session, tenant: Tenant, signed_in) -> None:
    _event(db, tenant, summary="Fractions équivalentes")
    _event(db, tenant, summary="Théorème de Pythagore")
    db.commit()

    body = client.get("/api/v1/timeline", params={"q": "pythagore"}).json()
    assert body["total"] == 1
    assert "Pythagore" in body["items"][0]["title"]


def test_a_date_range_bounds_the_agenda(client, db: Session, tenant: Tenant, signed_in) -> None:
    _event(db, tenant, summary="in range", days_ago=2)
    _event(db, tenant, summary="too old", days_ago=40)
    db.commit()

    since = (NOW - timedelta(days=7)).isoformat()
    body = client.get("/api/v1/timeline", params={"since": since}).json()
    assert [i["title"] for i in body["items"]] == ["in range"]


# --------------------------------------------------------------------------
# 3 · Tenancy — the boundary that actually leaked once (D23)
# --------------------------------------------------------------------------
def test_a_colleague_never_sees_another_teachers_class_events(
    client, db: Session, tenant: Tenant
) -> None:
    """A class is personal. Staffroom work (importing a textbook) is not, and
    is the deliberate exception: it belongs to no class and shows for everyone.
    """
    colleague = make_colleague(db, tenant)
    _event(db, tenant, summary="7B private sheet")
    event_service.record(
        db,
        school_id=tenant.school.id,
        kind=EventKind.SOURCE_IMPORTED,
        subject_type=EventSubject.SOURCE,
        subject_id=uuid.uuid4(),
        summary="shared textbook.pdf",
        actor_id=tenant.teacher.id,
        class_id=None,
        occurred_at=NOW,
    )
    db.commit()

    login(client, colleague.teacher.email)
    titles = [i["title"] for i in client.get("/api/v1/timeline").json()["items"]]
    assert "7B private sheet" not in titles
    assert "shared textbook.pdf" in titles


# --------------------------------------------------------------------------
# 4 · An event outlives what it describes
# --------------------------------------------------------------------------
def test_a_deleted_subject_still_shows_but_is_not_linkable(
    client, db: Session, tenant: Tenant, signed_in
) -> None:
    """Deleting a sheet does not un-print it. The line stays, with the stored
    summary, marked so the client does not offer a link that would 404."""
    _event(db, tenant, summary="a sheet that was later deleted")
    db.commit()

    item = client.get("/api/v1/timeline").json()["items"][0]
    assert item["title"] == "a sheet that was later deleted"
    assert item["resolved"] is False


# --------------------------------------------------------------------------
# 5 · Recording never breaks the thing being recorded
# --------------------------------------------------------------------------
def test_a_failing_record_returns_none_instead_of_raising(
    db: Session, tenant: Tenant, monkeypatch
) -> None:
    """An agenda line is worth less than the work it describes.

    A confirmed scan must never be lost because its log row would not write, so
    `record` swallows its own failure and returns None. Driven by making the
    write itself fail, rather than by a bad foreign key: SQLite does not enforce
    those by default, so that version of this test would pass for the wrong
    reason and go on passing if the guard were deleted.
    """

    def boom() -> None:
        raise RuntimeError("the database said no")

    monkeypatch.setattr(db, "flush", boom)
    result = event_service.record(
        db,
        school_id=tenant.school.id,
        kind=EventKind.SHEET_CREATED,
        subject_type=EventSubject.SHEET,
        subject_id=uuid.uuid4(),
        class_id=tenant.school_class.id,
        summary="doomed",
    )
    assert result is None


def test_the_summary_is_truncated_rather_than_refused(db: Session, tenant: Tenant) -> None:
    event = event_service.record(
        db,
        school_id=tenant.school.id,
        kind=EventKind.SHEET_CREATED,
        subject_type=EventSubject.SHEET,
        subject_id=uuid.uuid4(),
        class_id=tenant.school_class.id,
        summary="x" * 500,
    )
    assert event is not None
    assert len(event.summary) == event_service.MAX_SUMMARY


# --------------------------------------------------------------------------
# 6 · The log is written by the real paths, not only by tests
# --------------------------------------------------------------------------
def test_creating_a_sheet_through_the_api_lands_in_the_agenda(
    client, db: Session, tenant: Tenant, signed_in
) -> None:
    """The agenda is only worth anything if the product writes to it."""
    exercise = make_exercise(db, tenant, statement="Combien font 2 + 3 ?")
    response = client.post(
        "/api/v1/sheets",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
            "title": "Fractions, contrôle 1",
            "target": "class",
            "language": "fr",
            "items": [{"exercise_id": str(exercise.id), "position": 0}],
        },
    )
    assert response.status_code == 201, response.text

    body = client.get("/api/v1/timeline", params={"kind": "sheet_created"}).json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["title"] == "Fractions, contrôle 1"
    assert entry["resolved"] is True, "the sheet still exists, so it is linkable"
    assert entry["class_code"] == tenant.school_class.code
    assert entry["detail"]["items"] == 1
