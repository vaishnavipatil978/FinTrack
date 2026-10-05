import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken


def create(
    session: AsyncSession, *, user_id: int, token_hash: str, expires_at: datetime.datetime
) -> PasswordResetToken:
    token = PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    session.add(token)
    return token


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> PasswordResetToken | None:
    result = await session.execute(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    )
    return result.scalar_one_or_none()
