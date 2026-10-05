from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


def create(session: AsyncSession, *, email: str, hashed_password: str, full_name: str) -> User:
    user = User(email=email.lower(), hashed_password=hashed_password, full_name=full_name)
    session.add(user)
    return user


async def list_users(
    session: AsyncSession,
    *,
    is_locked: bool | None,
    search: str | None,
    page: int,
    page_size: int,
) -> tuple[list[User], int]:
    """Admin-only listing (FR-ADMIN-01) - never scoped by requester, since the requester
    here is the admin, not the subject. Deliberately returns no financial data - just the
    columns a support workflow needs (FR-ADMIN-03: no bypass into another user's ledger).
    """
    conditions: list[ColumnElement[bool]] = []
    if is_locked is not None:
        conditions.append(User.is_locked.is_(is_locked))
    if search:
        term = f"%{search}%"
        conditions.append(or_(User.email.ilike(term), User.full_name.ilike(term)))

    total = (
        await session.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar_one()
    result = await session.execute(
        select(User)
        .where(*conditions)
        .order_by(User.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total
