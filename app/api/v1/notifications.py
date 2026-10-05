from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.notification import (
    NotificationListResponse,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
)
from app.schemas.pagination import total_pages
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_notification_service(
    session: AsyncSession = Depends(get_db_session),
) -> NotificationService:
    return NotificationService(session)


# Literal routes first - "/{notification_id}" would otherwise capture "read-all"/"preferences".
@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    is_read: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationListResponse:
    items, total = await service.list_for_user(
        user_id=current_user.id, is_read=is_read, page=page, page_size=page_size
    )
    return NotificationListResponse(
        items=[NotificationRead.model_validate(i, from_attributes=True) for i in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.get("/preferences", response_model=list[NotificationPreferenceRead])
async def get_preferences(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> list[NotificationPreferenceRead]:
    prefs = await service.get_preferences(user_id=current_user.id)
    return [NotificationPreferenceRead.model_validate(p, from_attributes=True) for p in prefs]


@router.patch("/preferences", response_model=list[NotificationPreferenceRead])
async def update_preferences(
    payload: list[NotificationPreferenceUpdate],
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> list[NotificationPreferenceRead]:
    prefs = await service.set_preferences(
        user_id=current_user.id,
        items=[(p.type, p.channel, p.is_enabled) for p in payload],
    )
    return [NotificationPreferenceRead.model_validate(p, from_attributes=True) for p in prefs]


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> None:
    await service.mark_all_read(user_id=current_user.id)


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> None:
    await service.mark_read(user_id=current_user.id, notification_id=notification_id)
