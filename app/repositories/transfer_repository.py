import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transfer import Transfer


def create(
    session: AsyncSession,
    *,
    user_id: int,
    from_account_id: int,
    to_account_id: int,
    amount: Decimal,
    currency: str,
    transfer_date: datetime.date,
    description: str | None,
) -> Transfer:
    transfer = Transfer(
        user_id=user_id,
        from_account_id=from_account_id,
        to_account_id=to_account_id,
        amount=amount,
        currency=currency,
        transfer_date=transfer_date,
        description=description,
    )
    session.add(transfer)
    return transfer


async def get_owned(session: AsyncSession, *, transfer_id: int, user_id: int) -> Transfer | None:
    result = await session.execute(
        select(Transfer).where(Transfer.id == transfer_id, Transfer.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    page: int,
    page_size: int,
) -> tuple[list[Transfer], int]:
    conditions = [Transfer.user_id == user_id]
    if account_id is not None:
        conditions.append(
            or_(Transfer.from_account_id == account_id, Transfer.to_account_id == account_id)
        )
    if date_from is not None:
        conditions.append(Transfer.transfer_date >= date_from)
    if date_to is not None:
        conditions.append(Transfer.transfer_date <= date_to)

    total = (
        await session.execute(select(func.count()).select_from(Transfer).where(*conditions))
    ).scalar_one()
    stmt = (
        select(Transfer)
        .where(*conditions)
        .order_by(Transfer.transfer_date.desc(), Transfer.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all()), total
