from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.category import Category
from app.models.enums import CategoryType
from app.models.user import User
from app.schemas.category import CategoryCreate, CategoryRead, CategoryUpdate
from app.services.category_service import CategoryService

router = APIRouter(prefix="/categories", tags=["Categories"])


def get_category_service(session: AsyncSession = Depends(get_db_session)) -> CategoryService:
    return CategoryService(session)


@router.get("", response_model=list[CategoryRead])
async def list_categories(
    type: CategoryType | None = Query(default=None),
    include_archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> list[Category]:
    return await category_service.list_visible_to_user(
        user=current_user, type=type, include_archived=include_archived
    )


@router.post("", response_model=CategoryRead, status_code=status.HTTP_201_CREATED)
async def create_category(
    payload: CategoryCreate,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> Category:
    return await category_service.create(user=current_user, payload=payload)


@router.patch("/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: int,
    payload: CategoryUpdate,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> Category:
    return await category_service.update(
        user=current_user, category_id=category_id, payload=payload
    )


@router.post("/{category_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_category(
    category_id: int,
    current_user: User = Depends(get_current_user),
    category_service: CategoryService = Depends(get_category_service),
) -> None:
    await category_service.archive(user=current_user, category_id=category_id)
