from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.models.category import Category
from app.models.enums import CategoryType
from app.models.user import User
from app.repositories import category_repository
from app.schemas.category import CategoryCreate, CategoryUpdate


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user: User, payload: CategoryCreate) -> Category:
        existing = await category_repository.get_by_name_for_user(
            self._session, name=payload.name, user_id=user.id
        )
        if existing is not None:
            raise ConflictError(
                "A category with this name already exists", code="CATEGORY_NAME_EXISTS"
            )
        category = category_repository.create(
            self._session, user_id=user.id, name=payload.name, type=payload.type
        )
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def list_visible_to_user(
        self, *, user: User, type: CategoryType | None, include_archived: bool
    ) -> list[Category]:
        return await category_repository.list_visible_to_user(
            self._session, user_id=user.id, type=type, include_archived=include_archived
        )

    async def get_visible_to_user(self, *, user: User, category_id: int) -> Category:
        category = await category_repository.get_visible_to_user(
            self._session, category_id=category_id, user_id=user.id
        )
        if category is None:
            raise NotFoundError("The requested category was not found", code="CATEGORY_NOT_FOUND")
        return category

    async def update(self, *, user: User, category_id: int, payload: CategoryUpdate) -> Category:
        category = await self.get_visible_to_user(user=user, category_id=category_id)
        if category.is_system:
            raise ForbiddenError(
                "System categories cannot be modified", code="CANNOT_MODIFY_SYSTEM_CATEGORY"
            )
        category.name = payload.name
        await self._session.commit()
        await self._session.refresh(category)
        return category

    async def archive(self, *, user: User, category_id: int) -> None:
        category = await self.get_visible_to_user(user=user, category_id=category_id)
        if category.is_system:
            raise ForbiddenError(
                "System categories cannot be modified", code="CANNOT_MODIFY_SYSTEM_CATEGORY"
            )
        if category.is_archived:
            return  # idempotent, consistent with AccountService.archive
        category.is_archived = True
        await self._session.commit()
