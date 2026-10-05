import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AccountType


def _validate_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
    return value.upper()


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: AccountType
    currency: str
    opening_balance: Decimal = Field(default=Decimal("0"), max_digits=18, decimal_places=2)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _validate_currency(value)


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    type: AccountType | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: AccountType
    currency: str
    balance: Decimal
    allow_negative_balance: bool
    is_archived: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


class AccountBalanceRead(BaseModel):
    account_id: int
    balance: Decimal
    currency: str
    as_of: datetime.datetime
