import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import CategoryType, RecurringFrequency, RecurringStatus
from app.models.recurring_rule import RecurringRule


def create(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    category_id: int | None,
    type: CategoryType,
    amount: Decimal,
    currency: str,
    description: str,
    frequency: RecurringFrequency,
    interval: int,
    start_date: datetime.date,
    end_date: datetime.date | None,
) -> RecurringRule:
    rule = RecurringRule(
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        type=type,
        amount=amount,
        currency=currency,
        description=description,
        frequency=frequency,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        next_run_date=start_date,
        status=RecurringStatus.ACTIVE,
    )
    session.add(rule)
    return rule


async def get_owned(session: AsyncSession, *, rule_id: int, user_id: int) -> RecurringRule | None:
    result = await session.execute(
        select(RecurringRule).where(RecurringRule.id == rule_id, RecurringRule.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession, *, user_id: int, status: RecurringStatus | None
) -> list[RecurringRule]:
    stmt = select(RecurringRule).where(RecurringRule.user_id == user_id)
    if status is not None:
        stmt = stmt.where(RecurringRule.status == status)
    stmt = stmt.order_by(RecurringRule.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_due(session: AsyncSession, *, as_of: datetime.date) -> list[RecurringRule]:
    """Rules the worker should process - active and due. Called from Celery, not scoped to
    a single user (the worker processes across all users in one sweep).
    """
    result = await session.execute(
        select(RecurringRule).where(
            RecurringRule.status == RecurringStatus.ACTIVE,
            RecurringRule.next_run_date <= as_of,
        )
    )
    return list(result.scalars().all())
