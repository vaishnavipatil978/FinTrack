import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.recurring_rule import RecurringRule


class RecurringOccurrence(Base):
    """The idempotency anchor for recurring-transaction processing.

    The UNIQUE(recurring_rule_id, scheduled_date) constraint - not application-level
    check-then-insert logic - is what makes worker retries/redelivery safe. See
    docs/database-design.md §3.11 and docs/architecture/data-flow.md §3.
    """

    __tablename__ = "recurring_occurrences"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurring_rule_id: Mapped[int] = mapped_column(ForeignKey("recurring_rules.id"), nullable=False)
    scheduled_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    # use_alter breaks the circular FK with transactions.recurring_occurrence_id.
    transaction_id: Mapped[int] = mapped_column(
        ForeignKey("transactions.id", use_alter=True), nullable=False
    )
    processed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    rule: Mapped["RecurringRule"] = relationship(back_populates="occurrences")

    __table_args__ = (
        UniqueConstraint(
            "recurring_rule_id", "scheduled_date", name="uq_recurring_occurrences_rule_date"
        ),
    )
