import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base, TimestampMixin
from app.models.enums import CategoryType, RecurringFrequency, RecurringStatus

if TYPE_CHECKING:
    from app.models.recurring_occurrence import RecurringOccurrence


class RecurringRule(TimestampMixin, Base):
    __tablename__ = "recurring_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    type: Mapped[CategoryType] = mapped_column(
        pg_enum(CategoryType, "category_type"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    frequency: Mapped[RecurringFrequency] = mapped_column(
        pg_enum(RecurringFrequency, "recurring_frequency"), nullable=False
    )
    interval: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    start_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    next_run_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[RecurringStatus] = mapped_column(
        pg_enum(RecurringStatus, "recurring_status"), nullable=False, default=RecurringStatus.ACTIVE
    )

    occurrences: Mapped[list["RecurringOccurrence"]] = relationship(back_populates="rule")

    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("interval > 0", name="positive_interval"),
        # The worker's due-rule query: WHERE status = ACTIVE AND next_run_date <= today.
        Index("ix_recurring_rules_status_next_run_date", "status", "next_run_date"),
    )
