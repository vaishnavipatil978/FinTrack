import datetime

import pytest

from app.models.enums import RecurringFrequency
from app.services.recurring_math import compute_next_run_date


@pytest.mark.parametrize(
    ("current", "frequency", "interval", "expected"),
    [
        (datetime.date(2026, 9, 5), RecurringFrequency.DAILY, 1, datetime.date(2026, 9, 6)),
        (datetime.date(2026, 9, 5), RecurringFrequency.DAILY, 7, datetime.date(2026, 9, 12)),
        (datetime.date(2026, 9, 5), RecurringFrequency.WEEKLY, 1, datetime.date(2026, 9, 12)),
        (datetime.date(2026, 9, 5), RecurringFrequency.WEEKLY, 2, datetime.date(2026, 9, 19)),
        (datetime.date(2026, 9, 5), RecurringFrequency.MONTHLY, 1, datetime.date(2026, 10, 5)),
        (datetime.date(2026, 1, 31), RecurringFrequency.MONTHLY, 1, datetime.date(2026, 2, 28)),
        (
            datetime.date(2024, 1, 31),
            RecurringFrequency.MONTHLY,
            1,
            datetime.date(2024, 2, 29),
        ),  # leap year
        (datetime.date(2026, 9, 5), RecurringFrequency.YEARLY, 1, datetime.date(2027, 9, 5)),
        (datetime.date(2024, 2, 29), RecurringFrequency.YEARLY, 1, datetime.date(2025, 2, 28)),
        (datetime.date(2026, 10, 31), RecurringFrequency.MONTHLY, 2, datetime.date(2026, 12, 31)),
    ],
)
def test_compute_next_run_date(
    current: datetime.date,
    frequency: RecurringFrequency,
    interval: int,
    expected: datetime.date,
) -> None:
    assert compute_next_run_date(current, frequency=frequency, interval=interval) == expected
