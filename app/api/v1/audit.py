import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.repositories import audit_repository
from app.schemas.notification import AuditListResponse, AuditLogRead
from app.schemas.pagination import total_pages

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("/me", response_model=AuditListResponse)
async def my_audit_trail(
    action: str | None = Query(default=None, max_length=64),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuditListResponse:
    items, total = await audit_repository.list_for_user(
        session,
        user_id=current_user.id,
        action=action,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return AuditListResponse(
        items=[AuditLogRead.model_validate(i, from_attributes=True) for i in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )
