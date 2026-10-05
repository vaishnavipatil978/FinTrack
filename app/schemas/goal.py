import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import GoalStatus


def _validate_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
    return value.upper()


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str
    current_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=2)
    target_date: datetime.date

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _validate_currency(value)


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    target_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    target_date: datetime.date | None = None


class GoalContributionCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    contributed_at: datetime.date
    source_account_id: int | None = None
    source_transaction_id: int | None = None


class GoalContributionRead(BaseModel):
    id: int
    goal_id: int
    amount: Decimal
    source_account_id: int | None
    source_transaction_id: int | None
    contributed_at: datetime.date
    created_at: datetime.datetime


class GoalContributionListResponse(BaseModel):
    items: list[GoalContributionRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class GoalRead(BaseModel):
    id: int
    name: str
    target_amount: Decimal
    current_amount: Decimal
    currency: str
    target_date: datetime.date
    status: GoalStatus
    progress_pct: Decimal
    remaining_amount: Decimal
    required_monthly_contribution: Decimal | None
    is_achieved: bool
    is_overdue: bool


class GoalListResponse(BaseModel):
    items: list[GoalRead]
    page: int
    page_size: int
    total: int
    total_pages: int
