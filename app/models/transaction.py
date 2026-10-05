import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base, TimestampMixin
from app.models.enums import TransactionType

if TYPE_CHECKING:
    from app.models.transfer import Transfer


class Transaction(TimestampMixin, Base):
    """The single ledger table - every income, expense, and transfer leg is one row here.

    See docs/database-design.md §3.5. Balance sign is derived from `type`, never stored
    negative: INCOME/TRANSFER_IN credit the account, EXPENSE/TRANSFER_OUT debit it.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    # Nullable: transfer legs may omit a category.
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    type: Mapped[TransactionType] = mapped_column(
        pg_enum(TransactionType, "transaction_type"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    merchant: Mapped[str | None] = mapped_column(String(150), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    transfer_id: Mapped[int | None] = mapped_column(ForeignKey("transfers.id"), nullable=True)
    # use_alter breaks the circular FK with recurring_occurrences.transaction_id: this
    # constraint is added via ALTER TABLE after both tables exist, not inline at CREATE TABLE.
    recurring_occurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey("recurring_occurrences.id", use_alter=True), nullable=True
    )
    is_voided: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    transfer: Mapped["Transfer | None"] = relationship(
        back_populates="legs", foreign_keys=[transfer_id]
    )

    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        Index("ix_transactions_user_id_transaction_date", "user_id", "transaction_date"),
        Index("ix_transactions_account_id_transaction_date", "account_id", "transaction_date"),
        Index(
            "ix_transactions_user_id_category_id_transaction_date",
            "user_id",
            "category_id",
            "transaction_date",
        ),
        Index("ix_transactions_transfer_id", "transfer_id"),
    )
