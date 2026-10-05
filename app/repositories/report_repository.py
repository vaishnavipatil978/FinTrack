"""Aggregate queries behind the reports API. Income and expense only: TRANSFER_IN/OUT legs are
moving the user's own money, not earning or spending it (docs/05-use-cases.md UC-11), so they are
excluded from every total here. Voided transactions are excluded everywhere.
"""

import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.category import Category
from app.models.enums import TransactionType
from app.models.transaction import Transaction

_SPENDING_TYPES = (TransactionType.INCOME, TransactionType.EXPENSE)


async def totals_by_type(
    session: AsyncSession, *, user_id: int, date_from: datetime.date, date_to: datetime.date
) -> dict[TransactionType, Decimal]:
    result = await session.execute(
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.user_id == user_id,
            Transaction.is_voided.is_(False),
            Transaction.type.in_(_SPENDING_TYPES),
            Transaction.transaction_date >= date_from,
            Transaction.transaction_date <= date_to,
        )
        .group_by(Transaction.type)
    )
    return {row[0]: Decimal(row[1]) for row in result.all()}


async def totals_by_category(
    session: AsyncSession,
    *,
    user_id: int,
    transaction_type: TransactionType,
    date_from: datetime.date,
    date_to: datetime.date,
) -> list[tuple[int, str, Decimal]]:
    result = await session.execute(
        select(Category.id, Category.name, func.sum(Transaction.amount))
        .join(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.is_voided.is_(False),
            Transaction.type == transaction_type,
            Transaction.transaction_date >= date_from,
            Transaction.transaction_date <= date_to,
        )
        .group_by(Category.id, Category.name)
        .order_by(func.sum(Transaction.amount).desc(), Category.name)
    )
    return [(int(row[0]), str(row[1]), Decimal(row[2])) for row in result.all()]


async def active_accounts(session: AsyncSession, *, user_id: int) -> list[Account]:
    result = await session.execute(
        select(Account)
        .where(Account.user_id == user_id, Account.is_archived.is_(False))
        .order_by(Account.id)
    )
    return list(result.scalars().all())
