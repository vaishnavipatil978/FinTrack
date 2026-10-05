import datetime
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


def create(
    session: AsyncSession,
    *,
    user_id: int,
    token_hash: str,
    family_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    expires_at: datetime.datetime,
    created_by_ip: str | None,
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        family_id=family_id,
        parent_id=parent_id,
        expires_at=expires_at,
        created_by_ip=created_by_ip,
    )
    session.add(token)
    return token


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> RefreshToken | None:
    result = await session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()


async def revoke(session: AsyncSession, token: RefreshToken) -> None:
    token.revoked_at = datetime.datetime.now(datetime.UTC)


async def revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    """Reuse detection (UC-02): revokes every still-active token descended from one login."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.datetime.now(datetime.UTC))
    )


async def revoke_all_for_user(session: AsyncSession, user_id: int) -> None:
    """Used on password change (security-architecture.md §1.4): force re-login everywhere."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.datetime.now(datetime.UTC))
    )
