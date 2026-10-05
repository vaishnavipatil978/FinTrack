from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserUpdate


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_profile(self, *, user: User, payload: UserUpdate) -> User:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(user, field, value)
        await self._session.commit()
        await self._session.refresh(user)
        return user
