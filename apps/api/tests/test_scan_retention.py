"""The scan-image retention window, end to end (D3).

The mechanism was complete and the number was 0 — keep forever — so the most
sensitive artifact this product holds, a photograph of a named child's
handwriting, accumulated without bound from the first pilot day. These tests pin
both halves of the fix: that there is a number, and that the number does
something.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant

from alppy import cli
from alppy.core.config import Settings
from alppy.models import Detection, Scan, ScanPage
from alppy.models.enums import DetectionOutcome, ScanStatus


def test_the_shipped_default_is_a_school_year_plus_a_term() -> None:
    """400 days, and NOT 0.

    0 was the right default for exactly as long as nothing enforced any number.
    Once the purge runs nightly, 0 stops meaning "we have not decided" and
    starts meaning "we decided to keep photographs of children forever"."""
    assert Settings(_env_file=None).scan_image_retention_days == 400


class _RecordingStorage:
    """Records what it was asked to delete. The real thing talks to S3."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, key: str) -> bool:
        self.deleted.append(key)
        return True


def _pile(
    db: Session,
    tenant: Tenant,
    *,
    age_days: int,
    status: ScanStatus = ScanStatus.CONFIRMED,
) -> tuple[Scan, ScanPage, Detection]:
    created = datetime.now(UTC) - timedelta(days=age_days)
    scan = Scan(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        original_filename="copies.pdf",
        storage_key=f"scans/{age_days}/copies.pdf",
        status=status,
        created_at=created,
    )
    db.add(scan)
    db.flush()
    page = ScanPage(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_id=scan.id,
        page_index=0,
        image_key=f"scans/{age_days}/page-000.png",
        registered=True,
    )
    db.add(page)
    db.flush()
    detection = Detection(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        scan_page_id=page.id,
        item_index=0,
        outcome=DetectionOutcome.DETECTED,
        crop_key=f"crops/{age_days}/item-000.png",
    )
    db.add(detection)
    db.flush()
    # `created_at` has a server default; the ORM will have overwritten an
    # explicit value on some paths, so state it again after the flush.
    scan.created_at = created
    # Committed, not flushed: `_purge_scan_images` closes the session it was
    # given in its own `finally`, which would roll an uncommitted pile back and
    # make every assertion below pass for the wrong reason.
    db.commit()
    return scan, page, detection


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> _RecordingStorage:
    recorder = _RecordingStorage()
    monkeypatch.setattr("alppy.storage.get_storage", lambda: recorder)
    return recorder


def test_a_pile_older_than_the_window_loses_its_images(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _, page, detection = _pile(db, tenant, age_days=500)

    assert cli._purge_scan_images(older_than_days=None, dry_run=False) == 0

    # Crops first: the most personal thing here and the least needed once a
    # verdict is stored.
    assert storage.deleted == [detection.crop_key, page.image_key]


def test_a_pile_inside_the_window_is_untouched(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    """A mark given in June is still appealable against the page the following
    spring — which is the whole reason the number is 400 and not 90."""
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _pile(db, tenant, age_days=399)

    cli._purge_scan_images(older_than_days=None, dry_run=False)
    assert storage.deleted == []


def test_a_pile_still_in_review_keeps_its_images_however_old_it_is(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    """A teacher who cannot see the page cannot finish reviewing it."""
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _pile(db, tenant, age_days=900, status=ScanStatus.NEEDS_REVIEW)

    cli._purge_scan_images(older_than_days=None, dry_run=False)
    assert storage.deleted == []


def test_the_grade_survives_the_purge(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    """What a purge takes is the ability to look at the paper again. The
    verdict, the transcription and the mark live on `Detection`."""
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _, _, detection = _pile(db, tenant, age_days=500)
    detection_id = detection.id

    cli._purge_scan_images(older_than_days=None, dry_run=False)

    assert db.get(Detection, detection_id) is not None


def test_zero_still_means_forever_and_says_so(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    """A school that wants no deletion sets 0, and the command refuses rather
    than falling back to the shipped default."""
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _pile(db, tenant, age_days=5000)

    assert cli._purge_scan_images(older_than_days=0, dry_run=False) == 0
    assert storage.deleted == []


def test_a_dry_run_counts_without_deleting(
    monkeypatch: pytest.MonkeyPatch, db: Session, tenant: Tenant, storage: _RecordingStorage
) -> None:
    """What an operator runs before trusting a window they have just set."""
    monkeypatch.setattr(cli, "admin_session", lambda: db)
    _pile(db, tenant, age_days=500)

    assert cli._purge_scan_images(older_than_days=None, dry_run=True) == 0
    assert storage.deleted == []
