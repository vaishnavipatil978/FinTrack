import datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TransactionType
from app.models.transaction import Transaction
from app.utils.money import quantize_money

SortBy = Literal["transaction_date", "amount"]
SortDir = Literal["asc", "desc"]


def create(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    category_id: int | None,
    type: TransactionType,
    amount: Decimal,
    currency: str,
    description: str,
    merchant: str | None,
    notes: str | None,
    transaction_date: datetime.date,
    transfer_id: int | None = None,
) -> Transaction:
    transaction = Transaction(
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        type=type,
        amount=amount,
        currency=currency,
        description=description,
        merchant=merchant,
        notes=notes,
        transaction_date=transaction_date,
        transfer_id=transfer_id,
    )
    session.add(transaction)
    return transaction


async def get_owned(
    session: AsyncSession, *, transaction_id: int, user_id: int
) -> Transaction | None:
    result = await session.execute(
        select(Transaction).where(Transaction.id == transaction_id, Transaction.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int | None,
    category_id: int | None,
    type: TransactionType | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    amount_min: Decimal | None,
    amount_max: Decimal | None,
    search: str | None,
    sort_by: SortBy,
    sort_dir: SortDir,
    page: int,
    page_size: int,
) -> tuple[list[Transaction], int]:
    conditions = [Transaction.user_id == user_id, Transaction.is_voided.is_(False)]
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if category_id is not None:
        conditions.append(Transaction.category_id == category_id)
    if type is not None:
        conditions.append(Transaction.type == type)
    if date_from is not None:
        conditions.append(Transaction.transaction_date >= date_from)
    if date_to is not None:
        conditions.append(Transaction.transaction_date <= date_to)
    if amount_min is not None:
        conditions.append(Transaction.amount >= amount_min)
    if amount_max is not None:
        conditions.append(Transaction.amount <= amount_max)
    if search:
        term = f"%{search}%"
        conditions.append(
            or_(Transaction.description.ilike(term), Transaction.merchant.ilike(term))
        )

    count_stmt = select(func.count()).select_from(Transaction).where(*conditions)
    total = (await session.execute(count_stmt)).scalar_one()

    sort_column = (
        Transaction.transaction_date if sort_by == "transaction_date" else Transaction.amount
    )
    order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()

    stmt = (
        select(Transaction)
        .where(*conditions)
        .order_by(order, Transaction.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total


async def sum_expense_for_category_period(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    date_from: datetime.date,
    date_to: datetime.date,
) -> Decimal:
    """Live budget-utilization figure (UC-06) - always computed from actual transactions,
    never a stored/cached total that could drift.
    """
    stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
        Transaction.user_id == user_id,
        Transaction.category_id == category_id,
        Transaction.type == TransactionType.EXPENSE,
        Transaction.is_voided.is_(False),
        Transaction.transaction_date >= date_from,
        Transaction.transaction_date <= date_to,
    )
    result = await session.execute(stmt)
    # COALESCE's fallback renders as a bare integer 0, not "0.00" - always quantize so this
    # matches every other monetary field's 2-decimal-place JSON representation.
    return quantize_money(Decimal(result.scalar_one()))
