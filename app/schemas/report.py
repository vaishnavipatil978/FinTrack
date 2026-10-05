from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import CategoryType
from app.schemas.budget import BudgetRead
from app.schemas.goal import GoalRead


class CategoryAmount(BaseModel):
    category_id: int
    category_name: str
    amount: Decimal


class MonthlySummary(BaseModel):
    period_month: int
    period_year: int
    total_income: Decimal
    total_expense: Decimal
    net_savings: Decimal
    top_categories: list[CategoryAmount]


class CategoryBreakdownItem(BaseModel):
    category_id: int
    category_name: str
    amount: Decimal
    pct_of_total: Decimal


class CategoryBreakdown(BaseModel):
    period_month: int
    period_year: int
    type: CategoryType
    total: Decimal
    items: list[CategoryBreakdownItem]


class AccountBalanceItem(BaseModel):
    account_id: int
    name: str
    currency: str
    balance: Decimal


class BalancesReport(BaseModel):
    accounts: list[AccountBalanceItem]
    totals_by_currency: dict[str, Decimal]


class BudgetsGoalsSnapshot(BaseModel):
    period_month: int
    period_year: int
    budgets: list[BudgetRead]
    goals: list[GoalRead]
