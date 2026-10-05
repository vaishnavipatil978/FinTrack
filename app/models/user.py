import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.account import Account
    from app.models.refresh_token import RefreshToken


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        pg_enum(UserRole, "user_role"), nullable=False, default=UserRole.USER
    )
    default_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Explicit, admin-controlled lock (FR-ADMIN-02) - persists until an admin unlocks.
    is_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # Automatic, self-expiring lockout from repeated failed logins (FR-AUTH-09) - distinct
    # from is_locked above. Login is blocked while either is active; see AuthService.
    locked_until: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    accounts: Mapped[list["Account"]] = relationship(back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user")
