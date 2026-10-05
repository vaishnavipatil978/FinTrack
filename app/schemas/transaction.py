import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TransactionType


class TransactionDirection(StrEnum):
    """What a client may request when creating a transaction - deliberately narrower than
    the full TransactionType column, which also holds TRANSFER_IN/TRANSFER_OUT: those two
    are only ever set internally by TransferService (see docs/database-design.md §3.5).
    """

    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


def _validate_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
    return value.upper()


class TransactionCreate(BaseModel):
    account_id: int
    type: TransactionDirection
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str
    category_id: int
    transaction_date: datetime.date
    description: str = Field(min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=150)
    notes: str | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _validate_currency(value)


class TransactionUpdate(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    category_id: int | None = None
    transaction_date: datetime.date | None = None
    description: str | None = Field(default=None, min_length=1, max_length=255)
    merchant: str | None = Field(default=None, max_length=150)
    notes: str | None = None


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    category_id: int | None
    type: TransactionType
    amount: Decimal
    currency: str
    description: str
    merchant: str | None
    notes: str | None
    transaction_date: datetime.date
    is_voided: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class TransactionListResponse(BaseModel):
    items: list[TransactionRead]
    page: int
    page_size: int
    total: int
    total_pages: int
