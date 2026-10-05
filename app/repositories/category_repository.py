from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.category import Category
from app.models.enums import CategoryType


def create(session: AsyncSession, *, user_id: int, name: str, type: CategoryType) -> Category:
    category = Category(user_id=user_id, name=name, type=type, is_system=False)
    session.add(category)
    return category


async def get_visible_to_user(
    session: AsyncSession, *, category_id: int, user_id: int
) -> Category | None:
    """A category is visible to a user if it's a system default or their own custom one -
    scoped query, defense in depth alongside the service-layer check (security-architecture.md §2).
    """
    result = await session.execute(
        select(Category).where(
            Category.id == category_id,
            or_(Category.user_id.is_(None), Category.user_id == user_id),
        )
    )
    return result.scalar_one_or_none()


async def list_visible_to_user(
    session: AsyncSession,
    *,
    user_id: int,
    type: CategoryType | None,
    include_archived: bool,
) -> list[Category]:
    stmt = select(Category).where(or_(Category.user_id.is_(None), Category.user_id == user_id))
    if type is not None:
        stmt = stmt.where(Category.type == type)
    if not include_archived:
        stmt = stmt.where(Category.is_archived.is_(False))
    stmt = stmt.order_by(Category.is_system.desc(), Category.name)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_by_name_for_user(
    session: AsyncSession, *, name: str, user_id: int
) -> Category | None:
    result = await session.execute(
        select(Category).where(Category.user_id == user_id, Category.name == name)
    )
    return result.scalar_one_or_none()


async def get_by_name_visible_to_user(
    session: AsyncSession, *, name: str, user_id: int, is_archived: bool = False
) -> Category | None:
    """Case-insensitive name match among system defaults or the user's own categories -
    used to resolve the "category" column during CSV import (UC-10). Prefers the user's own
    category over a same-named system one if both somehow matched (shouldn't normally
    happen - category names are unique per the uq_categories_* constraints).
    """
    result = await session.execute(
        select(Category)
        .where(
            or_(Category.user_id.is_(None), Category.user_id == user_id),
            Category.name.ilike(name),
            Category.is_archived.is_(is_archived),
        )
        .order_by(Category.user_id.is_(None))
    )
    return result.scalars().first()
