"""What a school has spent with a model provider, and the ceiling on it (D21).

`ModelCall.cost_estimate_chf` has been written on every call since the audit
table existed. Nothing has ever summed it, capped it or alerted on it — so
there was no spend limit of any kind: not per teacher, not per school, not
global. The shapes that make that expensive are already in the product: one
call per pupil for feedback, one per crop for open-answer grading, thousands
for a textbook ingest. A loop that retries, a teacher who holds a button, a
provider that starts failing in a way the retry path does not recognise — any
of them bills a school until somebody notices the invoice.

**A query and a guard, not a subsystem.** The numbers are in Postgres. This
module sums them over two windows and says whether the next call may proceed.

**Where it is enforced.** At the API boundary, on the routes that reach a
provider or queue a job that will — `deps.enforce_ai_budget`, beside the rate
limiter it belongs with. That gate is honest about its own limit: a job already
queued when the cap is reached still runs to completion. The alternative is
checking inside the provider call, which would abandon a class set half-graded
and leave a teacher with a pile that is partly marked. Bounding what can be
*started* is the version a teacher can be told about.

**A cap is not a bill.** `cost_estimate_chf` is an estimate from a local price
table, zero for a model the table does not know (`estimate_cost_chf` logs that
rather than hiding it). So this bounds what we believe was spent, which is the
right quantity for stopping a runaway and the wrong one for accounting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alppy.core.config import Settings, get_settings
from alppy.core.logging import get_logger
from alppy.models import ModelCall

log = get_logger(__name__)

#: Warn here rather than only at the ceiling. A school that hits a hard cap
#: mid-lesson has no warning and no recourse; one that crossed 80% yesterday
#: could have been told.
WARN_AT = 0.8


@dataclass(frozen=True, slots=True)
class Budget:
    """One school's spend against its two ceilings. 0 means no ceiling."""

    spent_today_chf: float
    spent_month_chf: float
    daily_cap_chf: float
    monthly_cap_chf: float

    @property
    def daily_exceeded(self) -> bool:
        return self.daily_cap_chf > 0 and self.spent_today_chf >= self.daily_cap_chf

    @property
    def monthly_exceeded(self) -> bool:
        return self.monthly_cap_chf > 0 and self.spent_month_chf >= self.monthly_cap_chf

    @property
    def exceeded(self) -> bool:
        return self.daily_exceeded or self.monthly_exceeded

    @property
    def window(self) -> str:
        """Which ceiling was hit — the caller needs it for the message."""
        return "monthly" if self.monthly_exceeded else "daily"

    def near_limit(self) -> str | None:
        """The window at 80% or more but not yet over, else None."""
        monthly_near = (
            self.monthly_cap_chf > 0
            and self.spent_month_chf >= self.monthly_cap_chf * WARN_AT
            and not self.monthly_exceeded
        )
        if monthly_near:
            return "monthly"
        daily_near = (
            self.daily_cap_chf > 0
            and self.spent_today_chf >= self.daily_cap_chf * WARN_AT
            and not self.daily_exceeded
        )
        return "daily" if daily_near else None


class AiBudgetError(Exception):
    """Raised by `assert_within_budget` when a ceiling is reached. Carries no prose for a browser.

    The API turns this into the `ai_budget_exceeded` code and the client owns
    the sentence (CLAUDE.md — a failure crosses as a code). The message here is
    for the log.
    """

    def __init__(self, budget: Budget) -> None:
        self.budget = budget
        super().__init__(
            f"{budget.window} AI budget reached: "
            f"{budget.spent_month_chf if budget.window == 'monthly' else budget.spent_today_chf}"
            f" CHF"
        )


def _spent_since(db: Session, *, school_id: uuid.UUID, since: datetime) -> float:
    total = db.execute(
        select(func.coalesce(func.sum(ModelCall.cost_estimate_chf), 0.0))
        .where(ModelCall.school_id == school_id)
        .where(ModelCall.created_at >= since)
    ).scalar_one()
    return float(total or 0.0)


def current_budget(
    db: Session, *, school_id: uuid.UUID, settings: Settings | None = None
) -> Budget:
    """Two sums and two ceilings.

    A rolling 24 hours and a rolling 30 days rather than calendar boundaries:
    a calendar month resets at midnight on the 1st, which is the one moment a
    runaway is guaranteed to be forgiven.
    """
    resolved = settings or get_settings()
    now = datetime.now(UTC)
    return Budget(
        spent_today_chf=_spent_since(db, school_id=school_id, since=now - timedelta(days=1)),
        spent_month_chf=_spent_since(db, school_id=school_id, since=now - timedelta(days=30)),
        daily_cap_chf=resolved.ai_daily_cap_chf,
        monthly_cap_chf=resolved.ai_monthly_cap_chf,
    )


def assert_within_budget(
    db: Session, *, school_id: uuid.UUID, settings: Settings | None = None
) -> Budget:
    """Raise `AiBudgetExceeded` if this school has hit a ceiling.

    Logs at 80% on the way past, so the first anybody hears of a cap is not the
    cap itself.
    """
    budget = current_budget(db, school_id=school_id, settings=settings)
    if budget.exceeded:
        log.warning(
            "ai.budget.exceeded",
            school_id=str(school_id),
            window=budget.window,
            spent_today_chf=round(budget.spent_today_chf, 4),
            spent_month_chf=round(budget.spent_month_chf, 4),
            daily_cap_chf=budget.daily_cap_chf,
            monthly_cap_chf=budget.monthly_cap_chf,
        )
        raise AiBudgetError(budget)
    near = budget.near_limit()
    if near is not None:
        log.warning(
            "ai.budget.near_limit",
            school_id=str(school_id),
            window=near,
            spent_today_chf=round(budget.spent_today_chf, 4),
            spent_month_chf=round(budget.spent_month_chf, 4),
            daily_cap_chf=budget.daily_cap_chf,
            monthly_cap_chf=budget.monthly_cap_chf,
        )
    return budget
