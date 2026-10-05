import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import CategoryType, RecurringFrequency, RecurringStatus


def _validate_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
    return value.upper()


class RecurringRuleCreate(BaseModel):
    account_id: int
    category_id: int | None = None
    type: CategoryType
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str
    description: str = Field(min_length=1, max_length=255)
    frequency: RecurringFrequency
    interval: int = Field(default=1, gt=0)
    start_date: datetime.date
    end_date: datetime.date | None = None

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _validate_currency(value)


class RecurringRuleUpdate(BaseModel):
    category_id: int | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    description: str | None = Field(default=None, min_length=1, max_length=255)
    frequency: RecurringFrequency | None = None
    interval: int | None = Field(default=None, gt=0)
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None


class RecurringRuleRead(BaseModel):
    id: int
    account_id: int
    category_id: int | None
    type: CategoryType
    amount: Decimal
    currency: str
    description: str
    frequency: RecurringFrequency
    interval: int
    start_date: datetime.date
    end_date: datetime.date | None
    next_run_date: datetime.date
    status: RecurringStatus


class RecurringOccurrenceRead(BaseModel):
    id: int
    recurring_rule_id: int
    scheduled_date: datetime.date
    transaction_id: int
    processed_at: datetime.datetime


class UpcomingOccurrence(BaseModel):
    scheduled_date: datetime.date
