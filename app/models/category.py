import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base
from app.models.enums import CategoryType

if TYPE_CHECKING:
    from app.models.user import User


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = system default category, visible to every user (see FR-CAT-01).
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    type: Mapped[CategoryType] = mapped_column(
        pg_enum(CategoryType, "category_type"), nullable=False
    )
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User | None"] = relationship()

    __table_args__ = (
        # A user's custom categories must be unique by name among that user's own rows.
        # Plain UniqueConstraint is sufficient here because Postgres treats NULLs as
        # distinct, so this never fires across two different users' rows.
        UniqueConstraint("user_id", "name", name="uq_categories_user_id_name"),
        # System categories (user_id IS NULL) must be globally unique by name; a partial
        # index is required for that half, since the constraint above never applies
        # across NULL user_id rows. Together these implement the intent of
        # UNIQUE(COALESCE(user_id, 0), name) from docs/database-design.md §3.4.
        Index(
            "uq_categories_system_name",
            "name",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
    )
