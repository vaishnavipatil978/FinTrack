import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def list_for_user(
    session: AsyncSession,
    *,
    user_id: int,
    action: str | None,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    page: int,
    page_size: int,
) -> tuple[list[AuditLog], int]:
    conditions = [AuditLog.user_id == user_id]
    if action is not None:
        conditions.append(AuditLog.action == action)
    if date_from is not None:
        conditions.append(
            AuditLog.created_at
            >= datetime.datetime.combine(date_from, datetime.time.min, tzinfo=datetime.UTC)
        )
    if date_to is not None:
        conditions.append(
            AuditLog.created_at
            < datetime.datetime.combine(
                date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=datetime.UTC
            )
        )
    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*conditions))
    ).scalar_one()
    result = await session.execute(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total


async def list_all(
    session: AsyncSession,
    *,
    action: str | None,
    page: int,
    page_size: int,
) -> tuple[list[AuditLog], int]:
    """Admin-only, cross-user audit view (FR-ADMIN-02) - deliberately no financial
    entity payloads are exposed here, only the same allowlisted metadata every
    other audit read uses.
    """
    conditions = []
    if action is not None:
        conditions.append(AuditLog.action == action)
    total = (
        await session.execute(select(func.count()).select_from(AuditLog).where(*conditions))
    ).scalar_one()
    result = await session.execute(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total
