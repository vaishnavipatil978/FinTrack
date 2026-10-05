from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_db_session
from app.models.user import User
from app.repositories import audit_repository
from app.schemas.admin import AdminUserListResponse, AdminUserRead
from app.schemas.notification import AuditListResponse, AuditLogRead
from app.schemas.pagination import total_pages
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_admin_service(session: AsyncSession = Depends(get_db_session)) -> AdminService:
    return AdminService(session)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    is_locked: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> AdminUserListResponse:
    items, total = await service.list_users(
        is_locked=is_locked, search=search, page=page, page_size=page_size
    )
    return AdminUserListResponse(
        items=[AdminUserRead.model_validate(u, from_attributes=True) for u in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.post("/users/{user_id}/lock", status_code=status.HTTP_204_NO_CONTENT)
async def lock_user(
    user_id: int,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    await service.lock_user(admin=admin, user_id=user_id)


@router.post("/users/{user_id}/unlock", status_code=status.HTTP_204_NO_CONTENT)
async def unlock_user(
    user_id: int,
    admin: User = Depends(require_admin),
    service: AdminService = Depends(get_admin_service),
) -> None:
    await service.unlock_user(admin=admin, user_id=user_id)


@router.get("/audit", response_model=AuditListResponse)
async def all_audit_logs(
    user_id: int | None = Query(default=None),
    action: str | None = Query(default=None, max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
) -> AuditListResponse:
    if user_id is not None:
        items, total = await audit_repository.list_for_user(
            session,
            user_id=user_id,
            action=action,
            date_from=None,
            date_to=None,
            page=page,
            page_size=page_size,
        )
    else:
        items, total = await audit_repository.list_all(
            session, action=action, page=page, page_size=page_size
        )
    return AuditListResponse(
        items=[AuditLogRead.model_validate(i, from_attributes=True) for i in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )
