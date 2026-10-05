import datetime
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories import (
    password_reset_token_repository,
    refresh_token_repository,
    user_repository,
)
from app.services.audit_service import AuditService


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _is_locked(user: User) -> bool:
    if user.is_locked:
        return True
    return user.locked_until is not None and user.locked_until > _now()


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def register(self, *, email: str, password: str, full_name: str) -> User:
        existing = await user_repository.get_by_email(self._session, email)
        if existing is not None:
            raise ConflictError(
                "A user with this email is already registered", code="EMAIL_ALREADY_REGISTERED"
            )
        user = user_repository.create(
            self._session,
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
        )
        await self._session.flush()
        AuditService.record(
            self._session,
            action="USER_REGISTERED",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
        )
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def authenticate(
        self, *, email: str, password: str, ip: str | None
    ) -> tuple[User, TokenPair]:
        user = await user_repository.get_by_email(self._session, email)

        if user is not None and _is_locked(user):
            raise ForbiddenError("This account is locked", code="ACCOUNT_LOCKED")

        if user is None or not verify_password(password, user.hashed_password):
            if user is not None:
                await self._register_failed_attempt(user)
                await self._session.commit()
            raise UnauthorizedError("Incorrect email or password", code="INVALID_CREDENTIALS")

        user.failed_login_attempts = 0
        user.locked_until = None
        tokens = await self._issue_token_pair(user, family_id=uuid.uuid4(), parent_id=None, ip=ip)
        AuditService.record(
            self._session, action="LOGIN", user_id=user.id, entity_type="user", entity_id=user.id
        )
        await self._session.commit()
        return user, tokens

    async def _register_failed_attempt(self, user: User) -> None:
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= self._settings.max_failed_login_attempts:
            user.locked_until = _now() + datetime.timedelta(
                minutes=self._settings.account_lockout_minutes
            )

    async def _issue_token_pair(
        self, user: User, *, family_id: uuid.UUID, parent_id: uuid.UUID | None, ip: str | None
    ) -> TokenPair:
        access_token = create_access_token(
            user_id=user.id,
            role=user.role.value,
            secret_key=self._settings.jwt_secret_key,
            algorithm=self._settings.jwt_algorithm,
            expires_minutes=self._settings.access_token_expire_minutes,
        )
        raw_refresh = generate_opaque_token()
        expires_at = _now() + datetime.timedelta(days=self._settings.refresh_token_expire_days)
        refresh_token_repository.create(
            self._session,
            user_id=user.id,
            token_hash=hash_opaque_token(raw_refresh),
            family_id=family_id,
            parent_id=parent_id,
            expires_at=expires_at,
            created_by_ip=ip,
        )
        return TokenPair(
            access_token=access_token,
            refresh_token=raw_refresh,
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    async def _get_valid_refresh_token(self, raw_refresh_token: str) -> RefreshToken:
        """Common lookup for refresh/logout - raises the same generic error either way,
        so a client can't distinguish "not found" from "expired" from "revoked".
        """
        token_hash = hash_opaque_token(raw_refresh_token)
        token = await refresh_token_repository.get_by_token_hash(self._session, token_hash)
        if token is None or token.expires_at <= _now():
            raise UnauthorizedError(
                "Invalid or expired refresh token", code="INVALID_REFRESH_TOKEN"
            )
        if token.revoked_at is not None:
            # Reuse of an already-rotated token: possible theft. Revoke the whole family -
            # see docs/architecture/data-flow.md §6 (UC-02).
            await refresh_token_repository.revoke_family(self._session, token.family_id)
            await self._session.commit()
            raise UnauthorizedError(
                "Invalid or expired refresh token", code="INVALID_REFRESH_TOKEN"
            )
        return token

    async def refresh(self, *, raw_refresh_token: str, ip: str | None) -> TokenPair:
        token = await self._get_valid_refresh_token(raw_refresh_token)

        user = await user_repository.get_by_id(self._session, token.user_id)
        if user is None or _is_locked(user):
            raise UnauthorizedError(
                "Invalid or expired refresh token", code="INVALID_REFRESH_TOKEN"
            )

        await refresh_token_repository.revoke(self._session, token)
        tokens = await self._issue_token_pair(
            user, family_id=token.family_id, parent_id=token.id, ip=ip
        )
        await self._session.commit()
        return tokens

    async def logout(self, *, raw_refresh_token: str | None, user: User) -> None:
        if raw_refresh_token is None:
            await refresh_token_repository.revoke_all_for_user(self._session, user.id)
        else:
            token_hash = hash_opaque_token(raw_refresh_token)
            token = await refresh_token_repository.get_by_token_hash(self._session, token_hash)
            if token is not None and token.user_id == user.id:
                await refresh_token_repository.revoke(self._session, token)
        AuditService.record(
            self._session, action="LOGOUT", user_id=user.id, entity_type="user", entity_id=user.id
        )
        await self._session.commit()

    async def change_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        if not verify_password(current_password, user.hashed_password):
            raise UnauthorizedError(
                "Current password is incorrect", code="INVALID_CURRENT_PASSWORD"
            )
        user.hashed_password = hash_password(new_password)
        # Force re-login everywhere - security-architecture.md §1.4: a stale session
        # shouldn't survive a password change.
        await refresh_token_repository.revoke_all_for_user(self._session, user.id)
        AuditService.record(
            self._session,
            action="PASSWORD_CHANGED",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
        )
        await self._session.commit()

    async def request_password_reset(self, *, email: str) -> str | None:
        """Returns the raw reset token for the caller to deliver (email, or a log line in
        dev - see docs/architecture/background-jobs.md). The HTTP layer must respond
        identically whether or not the account exists (security-architecture.md §1.4).
        """
        user = await user_repository.get_by_email(self._session, email)
        if user is None:
            return None

        raw_token = generate_opaque_token()
        expires_at = _now() + datetime.timedelta(
            minutes=self._settings.password_reset_token_expire_minutes
        )
        password_reset_token_repository.create(
            self._session,
            user_id=user.id,
            token_hash=hash_opaque_token(raw_token),
            expires_at=expires_at,
        )
        await self._session.commit()
        return raw_token

    async def reset_password(self, *, raw_reset_token: str, new_password: str) -> None:
        token_hash = hash_opaque_token(raw_reset_token)
        token = await password_reset_token_repository.get_by_token_hash(self._session, token_hash)
        now = _now()
        if token is None or token.used_at is not None or token.expires_at <= now:
            raise BusinessRuleError(
                "Reset token is invalid or expired", code="INVALID_OR_EXPIRED_RESET_TOKEN"
            )

        user = await user_repository.get_by_id(self._session, token.user_id)
        if user is None:
            raise BusinessRuleError(
                "Reset token is invalid or expired", code="INVALID_OR_EXPIRED_RESET_TOKEN"
            )

        user.hashed_password = hash_password(new_password)
        # A successful reset proves account ownership - clear any lockout too, so this
        # doubles as the self-service recovery path from a brute-force lockout.
        user.is_locked = False
        user.locked_until = None
        user.failed_login_attempts = 0
        token.used_at = now
        await refresh_token_repository.revoke_all_for_user(self._session, user.id)
        await self._session.commit()
