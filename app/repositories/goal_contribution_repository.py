import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal_contribution import GoalContribution


def create(
    session: AsyncSession,
    *,
    goal_id: int,
    amount: Decimal,
    contributed_at: datetime.date,
    source_account_id: int | None,
    source_transaction_id: int | None,
) -> GoalContribution:
    contribution = GoalContribution(
        goal_id=goal_id,
        amount=amount,
        contributed_at=contributed_at,
        source_account_id=source_account_id,
        source_transaction_id=source_transaction_id,
    )
    session.add(contribution)
    return contribution


async def list_for_goal(
    session: AsyncSession, *, goal_id: int, page: int, page_size: int
) -> tuple[list[GoalContribution], int]:
    total = (
        await session.execute(
            select(func.count())
            .select_from(GoalContribution)
            .where(GoalContribution.goal_id == goal_id)
        )
    ).scalar_one()
    stmt = (
        select(GoalContribution)
        .where(GoalContribution.goal_id == goal_id)
        .order_by(GoalContribution.contributed_at.desc(), GoalContribution.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
