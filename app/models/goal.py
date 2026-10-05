import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base, TimestampMixin
from app.models.enums import GoalStatus

if TYPE_CHECKING:
    from app.models.goal_contribution import GoalContribution


class Goal(TimestampMixin, Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[Decimal] = mapped_column(nullable=False)
    current_amount: Mapped[Decimal] = mapped_column(nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    target_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    status: Mapped[GoalStatus] = mapped_column(
        pg_enum(GoalStatus, "goal_status"), nullable=False, default=GoalStatus.ACTIVE
    )

    contributions: Mapped[list["GoalContribution"]] = relationship(back_populates="goal")

    __table_args__ = (
        CheckConstraint("target_amount > 0", name="positive_target_amount"),
        CheckConstraint("current_amount >= 0", name="non_negative_current_amount"),
    )
