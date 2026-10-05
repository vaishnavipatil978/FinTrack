import calendar
import datetime


def month_date_range(year: int, month: int) -> tuple[datetime.date, datetime.date]:
    """Inclusive [start, end] calendar-month date range, e.g. (2026-09-01, 2026-09-30)."""
    last_day = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, 1), datetime.date(year, month, last_day)
