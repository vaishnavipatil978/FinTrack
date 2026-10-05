"""Admin operations - FR-ADMIN-01/02. Deliberately thin: no endpoint here returns another
user's financial data, plaintext password, or active token (FR-ADMIN-03) - this service only
ever touches the users table's support-relevant columns.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.user import User
from app.repositories import refresh_token_repository, user_repository
from app.services.audit_service import AuditService


class AdminService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_users(
        self, *, is_locked: bool | None, search: str | None, page: int, page_size: int
    ) -> tuple[list[User], int]:
        return await user_repository.list_users(
            self._session, is_locked=is_locked, search=search, page=page, page_size=page_size
        )

    async def _get_user(self, user_id: int) -> User:
        user = await user_repository.get_by_id(self._session, user_id)
        if user is None:
            raise NotFoundError("The requested user was not found", code="USER_NOT_FOUND")
        return user

    async def lock_user(self, *, admin: User, user_id: int) -> None:
        user = await self._get_user(user_id)
        if user.id == admin.id:
            raise BusinessRuleError(
                "An admin cannot lock their own account", code="CANNOT_LOCK_SELF"
            )
        if user.is_locked:
            return  # idempotent
        user.is_locked = True
        # Locking out an active session matters more than the audit metadata here, so
        # revoke every refresh token too - an admin lock should take effect immediately,
        # not just block the next login.
        await refresh_token_repository.revoke_all_for_user(self._session, user.id)
        AuditService.record(
            self._session,
            action="ADMIN_USER_LOCKED",
            user_id=admin.id,
            entity_type="user",
            entity_id=user.id,
        )
        await self._session.commit()

    async def unlock_user(self, *, admin: User, user_id: int) -> None:
        user = await self._get_user(user_id)
        if not user.is_locked and user.locked_until is None:
            return  # idempotent
        user.is_locked = False
        user.locked_until = None
        user.failed_login_attempts = 0
        AuditService.record(
            self._session,
            action="ADMIN_USER_UNLOCKED",
            user_id=admin.id,
            entity_type="user",
            entity_id=user.id,
        )
        await self._session.commit()
