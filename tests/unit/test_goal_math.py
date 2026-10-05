import datetime
from decimal import Decimal

import pytest

from app.services.goal_math import compute_goal_progress, months_between_ceil

# --- months_between_ceil -----------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime.date(2026, 9, 22), datetime.date(2026, 9, 22), 0),
        (datetime.date(2026, 9, 22), datetime.date(2026, 9, 10), 0),  # end before start
        (datetime.date(2026, 9, 22), datetime.date(2026, 10, 22), 1),  # exact one month
        (datetime.date(2026, 9, 22), datetime.date(2026, 10, 5), 1),  # partial month rounds up
        (datetime.date(2026, 9, 22), datetime.date(2026, 12, 31), 4),  # 3mo + partial -> 4
        (datetime.date(2026, 9, 22), datetime.date(2027, 12, 31), 16),  # 15mo9d -> 16
        (datetime.date(2026, 1, 31), datetime.date(2026, 3, 1), 2),  # month-end edge case
    ],
)
def test_months_between_ceil(start: datetime.date, end: datetime.date, expected: int) -> None:
    assert months_between_ceil(start, end) == expected


# --- compute_goal_progress ----------------------------------------------


def test_progress_for_a_partially_funded_goal() -> None:
    result = compute_goal_progress(
        target_amount=Decimal("300000.00"),
        current_amount=Decimal("125000.00"),
        target_date=datetime.date(2027, 12, 31),
        today=datetime.date(2026, 9, 22),
    )

    assert result.progress_pct == Decimal("41.67")
    assert result.remaining_amount == Decimal("175000.00")
    assert result.required_monthly_contribution == Decimal("10937.50")  # 175000 / 16
    assert result.is_achieved is False
    assert result.is_overdue is False


def test_progress_for_an_exactly_achieved_goal() -> None:
    result = compute_goal_progress(
        target_amount=Decimal("100000.00"),
        current_amount=Decimal("100000.00"),
        target_date=datetime.date(2027, 1, 1),
        today=datetime.date(2026, 9, 22),
    )

    assert result.progress_pct == Decimal("100.00")
    assert result.remaining_amount == Decimal("0.00")
    assert result.required_monthly_contribution == Decimal("0.00")
    assert result.is_achieved is True
    assert result.is_overdue is False


def test_progress_for_a_goal_that_overshot_its_target() -> None:
    result = compute_goal_progress(
        target_amount=Decimal("100000.00"),
        current_amount=Decimal("150000.00"),
        target_date=datetime.date(2027, 1, 1),
        today=datetime.date(2026, 9, 22),
    )

    assert result.progress_pct == Decimal("150.00")
    assert result.is_achieved is True
    assert result.remaining_amount == Decimal("0.00")


def test_achieved_goal_is_achieved_even_if_target_date_already_passed() -> None:
    """An achieved goal is never "overdue" - reaching the target makes the date moot."""
    result = compute_goal_progress(
        target_amount=Decimal("100000.00"),
        current_amount=Decimal("100000.00"),
        target_date=datetime.date(2020, 1, 1),
        today=datetime.date(2026, 9, 22),
    )

    assert result.is_achieved is True
    assert result.is_overdue is False


def test_progress_for_an_overdue_unachieved_goal_has_no_monthly_figure() -> None:
    result = compute_goal_progress(
        target_amount=Decimal("100000.00"),
        current_amount=Decimal("40000.00"),
        target_date=datetime.date(2026, 1, 1),
        today=datetime.date(2026, 9, 22),
    )

    assert result.is_overdue is True
    assert result.is_achieved is False
    assert result.required_monthly_contribution is None
    assert result.remaining_amount == Decimal("60000.00")


def test_target_date_today_is_not_overdue_and_uses_at_least_one_month() -> None:
    """target_date == today: zero calendar months remain, but max(months_remaining, 1)
    per UC-08 means the full remaining amount is due this month, not a divide-by-zero."""
    result = compute_goal_progress(
        target_amount=Decimal("1000.00"),
        current_amount=Decimal("0.00"),
        target_date=datetime.date(2026, 9, 22),
        today=datetime.date(2026, 9, 22),
    )

    assert result.is_overdue is False
    assert result.required_monthly_contribution == Decimal("1000.00")


def test_zero_current_amount_gives_zero_progress() -> None:
    result = compute_goal_progress(
        target_amount=Decimal("5000.00"),
        current_amount=Decimal("0.00"),
        target_date=datetime.date(2027, 9, 22),
        today=datetime.date(2026, 9, 22),
    )

    assert result.progress_pct == Decimal("0.00")
