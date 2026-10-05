"""Pure next-run-date math - no I/O, no system clock access, so it can be unit tested with
fixed inputs/expected outputs, same rationale as goal_math.py. See docs/database-design.md
§3.10 and docs/architecture/data-flow.md §3.
"""

import calendar
import datetime

from app.models.enums import RecurringFrequency


def _add_months(d: datetime.date, months: int) -> datetime.date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return datetime.date(year, month, day)


def compute_next_run_date(
    current: datetime.date, *, frequency: RecurringFrequency, interval: int
) -> datetime.date:
    """The next scheduled date after `current`, per the rule's frequency/interval.
    Month/year arithmetic clamps the day-of-month to the target month's length (e.g. Jan 31
    + 1 month -> Feb 28/29), the same convention goal_math.py uses.
    """
    if frequency == RecurringFrequency.DAILY:
        return current + datetime.timedelta(days=interval)
    if frequency == RecurringFrequency.WEEKLY:
        return current + datetime.timedelta(weeks=interval)
    if frequency == RecurringFrequency.MONTHLY:
        return _add_months(current, interval)
    if frequency == RecurringFrequency.YEARLY:
        return _add_months(current, interval * 12)
    raise ValueError(f"Unhandled frequency: {frequency}")  # pragma: no cover - exhaustive enum
