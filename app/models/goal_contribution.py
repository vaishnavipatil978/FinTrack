import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.goal import Goal


class GoalContribution(CreatedAtMixin, Base):
    __tablename__ = "goal_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id"), nullable=False, index=True)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    source_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )
    source_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    contributed_at: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    goal: Mapped["Goal"] = relationship(back_populates="contributions")

    __table_args__ = (CheckConstraint("amount > 0", name="positive_amount"),)
