"""Notifications - FR-NOTIF-01..04, docs/architecture/background-jobs.md.

Business services call `notify()` and never talk to a provider directly. Delivery goes through
NotificationChannel implementations, so swapping the email provider later touches only
EmailChannel. Per-user, per-type, per-channel preferences are honoured; no row means enabled.
"""

from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.enums import NotificationChannel
from app.models.notification import Notification, NotificationPreference
from app.repositories import notification_repository

logger = structlog.get_logger(__name__)


class DeliveryChannel(Protocol):
    async def deliver(self, *, user_id: int, type: str, title: str, message: str) -> None: ...


class EmailChannel:
    """Development stand-in: logs the message instead of sending it. Replace with a real
    provider implementation for production; nothing else needs to change.
    """

    async def deliver(self, *, user_id: int, type: str, title: str, message: str) -> None:
        logger.info("email_notification_logged", user_id=user_id, type=type, title=title)


class NotificationService:
    def __init__(self, session: AsyncSession, email_channel: DeliveryChannel | None = None) -> None:
        self._session = session
        self._email = email_channel or EmailChannel()

    async def _enabled(self, *, user_id: int, type: str, channel: NotificationChannel) -> bool:
        preference = await notification_repository.get_preference(
            self._session, user_id=user_id, type=type, channel=channel
        )
        return True if preference is None else preference.is_enabled

    async def notify(
        self,
        *,
        user_id: int,
        type: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queues notifications on the caller's session, so they commit with the business write."""
        if await self._enabled(user_id=user_id, type=type, channel=NotificationChannel.IN_APP):
            notification_repository.create(
                self._session,
                user_id=user_id,
                type=type,
                title=title,
                message=message,
                metadata=metadata,
            )
        if await self._enabled(user_id=user_id, type=type, channel=NotificationChannel.EMAIL):
            await self._email.deliver(user_id=user_id, type=type, title=title, message=message)

    async def list_for_user(
        self, *, user_id: int, is_read: bool | None, page: int, page_size: int
    ) -> tuple[list[Notification], int]:
        return await notification_repository.list_for_user(
            self._session, user_id=user_id, is_read=is_read, page=page, page_size=page_size
        )

    async def mark_read(self, *, user_id: int, notification_id: int) -> None:
        notification = await notification_repository.get_owned(
            self._session, notification_id=notification_id, user_id=user_id
        )
        if notification is None:
            raise NotFoundError(
                "The requested notification was not found", code="NOTIFICATION_NOT_FOUND"
            )
        notification.is_read = True
        await self._session.commit()

    async def mark_all_read(self, *, user_id: int) -> None:
        await notification_repository.mark_all_read(self._session, user_id=user_id)
        await self._session.commit()

    async def get_preferences(self, *, user_id: int) -> list[NotificationPreference]:
        return await notification_repository.list_preferences(self._session, user_id=user_id)

    async def set_preferences(
        self, *, user_id: int, items: list[tuple[str, NotificationChannel, bool]]
    ) -> list[NotificationPreference]:
        for type, channel, enabled in items:
            preference = await notification_repository.get_preference(
                self._session, user_id=user_id, type=type, channel=channel
            )
            if preference is None:
                self._session.add(
                    NotificationPreference(
                        user_id=user_id, type=type, channel=channel, is_enabled=enabled
                    )
                )
            else:
                preference.is_enabled = enabled
        await self._session.commit()
        return await notification_repository.list_preferences(self._session, user_id=user_id)
