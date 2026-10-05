from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Budget(TimestampMixin, Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    __table_args__ = (
        CheckConstraint("target_amount > 0", name="positive_target_amount"),
        CheckConstraint("period_month BETWEEN 1 AND 12", name="valid_period_month"),
        # One budget per category per period - FR-BUDG-01, enforced at the DB level.
        UniqueConstraint(
            "user_id",
            "category_id",
            "period_month",
            "period_year",
            name="uq_budgets_user_category_period",
        ),
    )
