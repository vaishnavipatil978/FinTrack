import datetime
from typing import Annotated

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ReportCache
from app.core.config import Settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import InvalidTokenError, decode_access_token
from app.db.session import get_db_session
from app.models.enums import UserRole
from app.models.user import User
from app.repositories import user_repository
from app.services.auth_service import AuthService
from app.services.user_service import UserService


def get_app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _is_locked(user: User) -> bool:
    if user.is_locked:
        return True
    return user.locked_until is not None and user.locked_until > datetime.datetime.now(datetime.UTC)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> User:
    if authorization is None or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_access_token(
            token, secret_key=settings.jwt_secret_key, algorithm=settings.jwt_algorithm
        )
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired access token") from exc

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired access token") from exc

    user = await user_repository.get_by_id(session, user_id)
    if user is None:
        raise UnauthorizedError("Invalid or expired access token")
    if _is_locked(user):
        raise ForbiddenError("This account is locked", code="ACCOUNT_LOCKED")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.ADMIN:
        raise ForbiddenError("This action requires administrator privileges")
    return user


def get_auth_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> AuthService:
    return AuthService(session, settings)


def get_user_service(session: AsyncSession = Depends(get_db_session)) -> UserService:
    return UserService(session)


def get_report_cache(request: Request) -> ReportCache:
    settings: Settings = request.app.state.settings
    return ReportCache(request.app.state.redis, enabled=settings.cache_enabled)


def get_idempotency_context(request: Request) -> tuple[Redis | None, bool, int]:
    settings: Settings = request.app.state.settings
    return request.app.state.redis, settings.cache_enabled, settings.idempotency_ttl_seconds
