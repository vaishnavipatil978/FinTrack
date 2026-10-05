"""Pure, deterministic goal-progress math - no I/O, no system clock access.

`today` is always passed in explicitly (never read from datetime.now() in here) so this
module can be unit tested with fixed inputs/expected outputs, per the Stage 6 acceptance
criterion in docs/06-development-roadmap.md. See docs/05-use-cases.md UC-08 for the formulas.
"""

import calendar
import datetime
from dataclasses import dataclass
from decimal import Decimal

from app.utils.money import quantize_money

_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class GoalProgress:
    progress_pct: Decimal
    remaining_amount: Decimal
    required_monthly_contribution: Decimal | None  # None when overdue and not achieved
    is_achieved: bool
    is_overdue: bool


def _add_months(d: datetime.date, months: int) -> datetime.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def months_between_ceil(start: datetime.date, end: datetime.date) -> int:
    """Whole months from start to end, rounded UP for any partial month - so a required
    monthly contribution is never underestimated by treating a partial final month as free.
    """
    if end <= start:
        return 0
    whole = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        whole -= 1
    whole = max(whole, 0)
    if _add_months(start, whole) < end:
        whole += 1
    return whole


def compute_goal_progress(
    *,
    target_amount: Decimal,
    current_amount: Decimal,
    target_date: datetime.date,
    today: datetime.date,
) -> GoalProgress:
    is_achieved = current_amount >= target_amount
    remaining = max(target_amount - current_amount, Decimal("0"))
    progress_pct = quantize_money(current_amount / target_amount * _HUNDRED)

    if is_achieved:
        return GoalProgress(
            progress_pct=progress_pct,
            remaining_amount=Decimal("0.00"),
            required_monthly_contribution=Decimal("0.00"),
            is_achieved=True,
            is_overdue=False,
        )

    is_overdue = target_date < today
    if is_overdue:
        # UC-08 alt-flow: a divide-by-zero/negative-months calculation is meaningless here -
        # the client shows an "overdue" state instead of a monthly-contribution figure.
        return GoalProgress(
            progress_pct=progress_pct,
            remaining_amount=remaining,
            required_monthly_contribution=None,
            is_achieved=False,
            is_overdue=True,
        )

    months_remaining = max(months_between_ceil(today, target_date), 1)
    required = quantize_money(remaining / Decimal(months_remaining))
    return GoalProgress(
        progress_pct=progress_pct,
        remaining_amount=remaining,
        required_monthly_contribution=required,
        is_achieved=False,
        is_overdue=False,
    )
