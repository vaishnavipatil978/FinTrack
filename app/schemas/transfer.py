import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransferCreate(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str
    transfer_date: datetime.date
    description: str | None = Field(default=None, max_length=255)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha():
            raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
        return value.upper()


class TransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    from_account_id: int
    to_account_id: int
    amount: Decimal
    currency: str
    description: str | None
    transfer_date: datetime.date
    created_at: datetime.datetime


class TransferListResponse(BaseModel):
    items: list[TransferRead]
    page: int
    page_size: int
    total: int
    total_pages: int
