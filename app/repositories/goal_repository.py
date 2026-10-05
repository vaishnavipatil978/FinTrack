import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import GoalStatus
from app.models.goal import Goal


def create(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    target_amount: Decimal,
    current_amount: Decimal,
    currency: str,
    target_date: datetime.date,
    status: GoalStatus,
) -> Goal:
    goal = Goal(
        user_id=user_id,
        name=name,
        target_amount=target_amount,
        current_amount=current_amount,
        currency=currency,
        target_date=target_date,
        status=status,
    )
    session.add(goal)
    return goal


async def get_owned(session: AsyncSession, *, goal_id: int, user_id: int) -> Goal | None:
    result = await session.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    status: GoalStatus | None,
    page: int,
    page_size: int,
) -> tuple[list[Goal], int]:
    conditions = [Goal.user_id == user_id]
    if status is not None:
        conditions.append(Goal.status == status)

    total = (
        await session.execute(select(func.count()).select_from(Goal).where(*conditions))
    ).scalar_one()
    stmt = (
        select(Goal)
        .where(*conditions)
        .order_by(Goal.target_date, Goal.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
