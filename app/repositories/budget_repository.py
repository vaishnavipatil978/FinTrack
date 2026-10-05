from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import Budget


def create(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    target_amount: Decimal,
    currency: str,
    period_month: int,
    period_year: int,
) -> Budget:
    budget = Budget(
        user_id=user_id,
        category_id=category_id,
        target_amount=target_amount,
        currency=currency,
        period_month=period_month,
        period_year=period_year,
    )
    session.add(budget)
    return budget


async def get_owned(session: AsyncSession, *, budget_id: int, user_id: int) -> Budget | None:
    result = await session.execute(
        select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_for_period(
    session: AsyncSession, *, user_id: int, category_id: int, period_month: int, period_year: int
) -> Budget | None:
    result = await session.execute(
        select(Budget).where(
            Budget.user_id == user_id,
            Budget.category_id == category_id,
            Budget.period_month == period_month,
            Budget.period_year == period_year,
        )
    )
    return result.scalar_one_or_none()


async def list_for_period(
    session: AsyncSession, *, user_id: int, period_month: int, period_year: int
) -> list[Budget]:
    result = await session.execute(
        select(Budget)
        .where(
            Budget.user_id == user_id,
            Budget.period_month == period_month,
            Budget.period_year == period_year,
        )
        .order_by(Budget.id)
    )
    return list(result.scalars().all())


async def delete(session: AsyncSession, budget: Budget) -> None:
    await session.delete(budget)
