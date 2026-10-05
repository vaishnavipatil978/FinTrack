from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.enums import AccountType


def create(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    type: AccountType,
    currency: str,
    balance: Decimal,
    allow_negative_balance: bool,
) -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        type=type,
        currency=currency,
        balance=balance,
        allow_negative_balance=allow_negative_balance,
    )
    session.add(account)
    return account


async def get_owned(session: AsyncSession, *, account_id: int, user_id: int) -> Account | None:
    """Scoped by user_id - defense in depth alongside the service-layer ownership check
    (security-architecture.md §2): even if the service check were ever skipped, this query
    could not return another user's row.
    """
    result = await session.execute(
        select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_by_name_for_user(session: AsyncSession, *, name: str, user_id: int) -> Account | None:
    """Case-insensitive name match, scoped to the user - used to resolve the "account"
    column during CSV import (UC-10), where the client refers to accounts by name.
    """
    result = await session.execute(
        select(Account).where(Account.user_id == user_id, Account.name.ilike(name))
    )
    return result.scalars().first()


async def list_for_user(
    session: AsyncSession, *, user_id: int, include_archived: bool
) -> list[Account]:
    stmt = select(Account).where(Account.user_id == user_id).order_by(Account.id)
    if not include_archived:
        stmt = stmt.where(Account.is_archived.is_(False))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_owned_for_update(
    session: AsyncSession, *, account_id: int, user_id: int
) -> Account | None:
    """Row-locks the account for the duration of the enclosing DB transaction, so a
    concurrent request touching the same account's balance is serialized behind this one
    rather than racing it (lost-update prevention - FR-ACCT-04, docs/architecture/data-flow.md §1).
    """
    result = await session.execute(
        select(Account)
        .where(Account.id == account_id, Account.user_id == user_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def lock_owned_accounts(
    session: AsyncSession, *, account_ids: list[int], user_id: int
) -> dict[int, Account]:
    """Locks multiple accounts at once, always in ascending id order regardless of the
    order requested, so two transfers racing in opposite directions between the same pair
    of accounts can never deadlock (docs/architecture/data-flow.md §2).
    """
    ordered_ids = sorted(set(account_ids))
    result = await session.execute(
        select(Account)
        .where(Account.id.in_(ordered_ids), Account.user_id == user_id)
        .order_by(Account.id)
        .with_for_update()
    )
    return {account.id: account for account in result.scalars().all()}
