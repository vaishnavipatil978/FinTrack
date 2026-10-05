from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import NotificationChannel
from app.models.notification import Notification, NotificationPreference


def create(
    session: AsyncSession,
    *,
    user_id: int,
    type: str,
    title: str,
    message: str,
    metadata: dict[str, object] | None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        message=message,
        is_read=False,
        notification_metadata=metadata,
    )
    session.add(notification)
    return notification


async def get_owned(
    session: AsyncSession, *, notification_id: int, user_id: int
) -> Notification | None:
    result = await session.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_for_user(
    session: AsyncSession, *, user_id: int, is_read: bool | None, page: int, page_size: int
) -> tuple[list[Notification], int]:
    conditions = [Notification.user_id == user_id]
    if is_read is not None:
        conditions.append(Notification.is_read.is_(is_read))
    total = (
        await session.execute(select(func.count()).select_from(Notification).where(*conditions))
    ).scalar_one()
    result = await session.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars().all()), total


async def mark_all_read(session: AsyncSession, *, user_id: int) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read.is_(False))
        .values(is_read=True)
    )


async def get_preference(
    session: AsyncSession, *, user_id: int, type: str, channel: NotificationChannel
) -> NotificationPreference | None:
    result = await session.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.type == type,
            NotificationPreference.channel == channel,
        )
    )
    return result.scalar_one_or_none()


async def list_preferences(session: AsyncSession, *, user_id: int) -> list[NotificationPreference]:
    result = await session.execute(
        select(NotificationPreference)
        .where(NotificationPreference.user_id == user_id)
        .order_by(NotificationPreference.id)
    )
    return list(result.scalars().all())
