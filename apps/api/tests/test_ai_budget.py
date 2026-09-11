"""The model-spend ceiling (D21).

`cost_estimate_chf` was written on every call and never summed, so there was no
spend limit of any kind — not per teacher, not per school, not global. The
shapes that make that expensive are already in the product: one call per pupil
for feedback, one per crop for grading, thousands for a textbook ingest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_api_fixtures import *  # noqa: F403
from test_api_fixtures import Tenant, login

from alppy.ai.spend import AiBudgetError, assert_within_budget, current_budget
from alppy.core.config import Settings
from alppy.models import ModelCall


def _call(db: Session, tenant: Tenant, *, chf: float, age_days: float = 0.0) -> ModelCall:
    row = ModelCall(
        id=uuid.uuid4(),
        school_id=tenant.school.id,
        provider="openai",
        model="gpt-5",
        purpose="generate_exercise",
        prompt_sha256="0" * 64,
        cost_estimate_chf=chf,
        ok=True,
    )
    db.add(row)
    db.flush()
    row.created_at = datetime.now(UTC) - timedelta(days=age_days)
    db.flush()
    return row


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# --- the sums ---------------------------------------------------------------


def test_a_quiet_school_is_far_from_both_ceilings(db: Session, tenant: Tenant) -> None:
    budget = current_budget(db, school_id=tenant.school.id, settings=_settings())
    assert budget.spent_today_chf == 0.0
    assert budget.exceeded is False


def test_the_daily_window_rolls_rather_than_resetting_at_midnight(
    db: Session, tenant: Tenant
) -> None:
    """A calendar boundary is the one moment a runaway is guaranteed to be
    forgiven."""
    _call(db, tenant, chf=5.0, age_days=0.5)
    _call(db, tenant, chf=5.0, age_days=2.0)

    budget = current_budget(db, school_id=tenant.school.id, settings=_settings())
    assert budget.spent_today_chf == pytest.approx(5.0)
    assert budget.spent_month_chf == pytest.approx(10.0)


def test_another_school_is_another_budget(
    db: Session, tenant: Tenant, other_tenant: Tenant
) -> None:
    _call(db, tenant, chf=50.0)
    budget = current_budget(db, school_id=other_tenant.school.id, settings=_settings())
    assert budget.spent_today_chf == 0.0


# --- the ceiling ------------------------------------------------------------


def test_the_daily_ceiling_refuses(db: Session, tenant: Tenant) -> None:
    _call(db, tenant, chf=20.0)
    with pytest.raises(AiBudgetError) as caught:
        assert_within_budget(db, school_id=tenant.school.id, settings=_settings())
    assert caught.value.budget.window == "daily"


def test_the_monthly_ceiling_refuses_even_on_a_quiet_day(
    db: Session, tenant: Tenant
) -> None:
    """Twenty busy days at nineteen francs is under every daily cap and four
    times the monthly one."""
    for day in range(1, 21):
        _call(db, tenant, chf=19.0, age_days=float(day))
    with pytest.raises(AiBudgetError) as caught:
        assert_within_budget(db, school_id=tenant.school.id, settings=_settings())
    assert caught.value.budget.window == "monthly"
    assert caught.value.budget.daily_exceeded is False


def test_zero_means_no_ceiling(db: Session, tenant: Tenant) -> None:
    """A school on its own provider account sets 0 and is not second-guessed."""
    _call(db, tenant, chf=10_000.0)
    settings = _settings(ai_daily_cap_chf=0.0, ai_monthly_cap_chf=0.0)
    assert assert_within_budget(db, school_id=tenant.school.id, settings=settings).exceeded is False


def test_eighty_percent_is_reported_before_the_wall(db: Session, tenant: Tenant) -> None:
    """A school that hits a hard cap mid-lesson has no warning and no recourse;
    one that crossed 80% yesterday could have been told."""
    _call(db, tenant, chf=17.0)
    budget = assert_within_budget(db, school_id=tenant.school.id, settings=_settings())
    assert budget.near_limit() == "daily"


def test_below_eighty_percent_says_nothing(db: Session, tenant: Tenant) -> None:
    _call(db, tenant, chf=5.0)
    budget = assert_within_budget(db, school_id=tenant.school.id, settings=_settings())
    assert budget.near_limit() is None


def test_the_shipped_ceilings_leave_room_for_a_textbook(db: Session, tenant: Tenant) -> None:
    """A full ingest is on the order of 10 CHF. A default that refused one
    would be a cap nobody could run the product under, which is worse than no
    cap: it gets raised to infinity on the first bad afternoon."""
    settings = _settings()
    assert settings.ai_daily_cap_chf >= 20.0
    assert settings.ai_monthly_cap_chf >= 10 * settings.ai_daily_cap_chf / 2


# --- at the boundary --------------------------------------------------------


def test_an_exhausted_school_cannot_queue_more_work(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    """402, not 429: this is not "slow down", it is "not until the window rolls
    or somebody raises the cap", and a client retrying on 429 would hammer a
    door that is not going to open."""
    login(client, tenant.teacher.email)
    _call(db, tenant, chf=25.0)
    db.commit()

    response = client.post(
        "/api/v1/sheets/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
        },
    )
    assert response.status_code == 402
    body = response.json()["error"]
    assert body["code"] == "ai_budget_exceeded"
    assert body["details"]["window"] == "daily"
    # The teacher-facing sentence is the client's; this carries the facts.
    assert body["details"]["cap_chf"] == 20.0


def test_a_school_inside_its_budget_is_not_stopped(
    client: TestClient, db: Session, tenant: Tenant
) -> None:
    login(client, tenant.teacher.email)
    _call(db, tenant, chf=1.0)
    db.commit()

    response = client.post(
        "/api/v1/sheets/propose",
        json={
            "class_id": str(tenant.school_class.id),
            "subject_id": str(tenant.subject.id),
        },
    )
    assert response.status_code != 402


# --- the audit trail's own window -------------------------------------------
# `ModelCall` had no retention window at all, which on the one table written for
# every single model call is an unbounded table rather than a decision to keep.


def test_the_audit_trail_keeps_three_years_by_default() -> None:
    """Long on purpose. It is what a school shows an auditor to answer "did any
    of our data go to provider X", and that question arrives late — a
    procurement review asks about the year before last. It can afford to be
    long because the row is content-free by construction."""
    assert Settings(_env_file=None).model_call_retention_days == 1095


def test_rows_past_the_window_go(db: Session, tenant: Tenant) -> None:
    from alppy.ai.audit import purge_expired_calls

    _call(db, tenant, chf=1.0, age_days=1200.0)
    kept = _call(db, tenant, chf=1.0, age_days=10.0)
    db.commit()

    assert purge_expired_calls(db) == 1
    db.commit()
    assert db.get(ModelCall, kept.id) is not None


def test_zero_keeps_the_trail_forever(
    db: Session, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An audit trail whose default is "quietly disappears" is not one, so this
    is opt-OUT and a school that wants everything kept sets 0."""
    from alppy.ai import audit

    _call(db, tenant, chf=1.0, age_days=5000.0)
    db.commit()
    monkeypatch.setattr(
        audit, "get_settings", lambda: Settings(_env_file=None, model_call_retention_days=0)
    )
    assert audit.purge_expired_calls(db) == 0
