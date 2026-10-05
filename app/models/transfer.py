import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class Transfer(CreatedAtMixin, Base):
    """The atomic parent record linking the two Transaction legs of a transfer.

    See docs/database-design.md §3.6 and docs/architecture/data-flow.md §2.
    """

    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transfer_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)

    legs: Mapped[list["Transaction"]] = relationship(
        back_populates="transfer", foreign_keys="Transaction.transfer_id"
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("to_account_id <> from_account_id", name="distinct_accounts"),
    )
