import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recurring_occurrence import RecurringOccurrence


def create(
    session: AsyncSession,
    *,
    recurring_rule_id: int,
    scheduled_date: datetime.date,
    transaction_id: int,
) -> RecurringOccurrence:
    occurrence = RecurringOccurrence(
        recurring_rule_id=recurring_rule_id,
        scheduled_date=scheduled_date,
        transaction_id=transaction_id,
    )
    session.add(occurrence)
    return occurrence


async def get_by_rule_and_date(
    session: AsyncSession, *, recurring_rule_id: int, scheduled_date: datetime.date
) -> RecurringOccurrence | None:
    result = await session.execute(
        select(RecurringOccurrence).where(
            RecurringOccurrence.recurring_rule_id == recurring_rule_id,
            RecurringOccurrence.scheduled_date == scheduled_date,
        )
    )
    return result.scalar_one_or_none()


async def list_for_rule(
    session: AsyncSession, *, recurring_rule_id: int
) -> list[RecurringOccurrence]:
    result = await session.execute(
        select(RecurringOccurrence)
        .where(RecurringOccurrence.recurring_rule_id == recurring_rule_id)
        .order_by(RecurringOccurrence.scheduled_date.desc())
    )
    return list(result.scalars().all())
