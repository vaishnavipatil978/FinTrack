from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


def _validate_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha():
        raise ValueError("Currency must be a 3-letter ISO 4217 code, e.g. INR")
    return value.upper()


class BudgetCreate(BaseModel):
    category_id: int
    target_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str
    period_month: int = Field(ge=1, le=12)
    period_year: int = Field(ge=2000, le=2100)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        return _validate_currency(value)


class BudgetUpdate(BaseModel):
    target_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class BudgetRead(BaseModel):
    id: int
    category_id: int
    target_amount: Decimal
    currency: str
    period_month: int
    period_year: int
    spent: Decimal
    remaining: Decimal
    utilization_pct: Decimal
    is_overspent: bool


class BudgetSummaryCategory(BaseModel):
    budget_id: int
    category_id: int
    category_name: str
    target_amount: Decimal
    spent: Decimal
    remaining: Decimal
    utilization_pct: Decimal
    is_overspent: bool


class BudgetSummaryResponse(BaseModel):
    period_month: int
    period_year: int
    total_budgeted: Decimal
    total_spent: Decimal
    categories: list[BudgetSummaryCategory]
