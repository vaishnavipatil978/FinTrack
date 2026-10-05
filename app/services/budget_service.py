import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, ConflictError, NotFoundError
from app.models.budget import Budget
from app.models.user import User
from app.repositories import budget_repository, category_repository, transaction_repository
from app.schemas.budget import (
    BudgetCreate,
    BudgetRead,
    BudgetSummaryCategory,
    BudgetSummaryResponse,
    BudgetUpdate,
)
from app.services.audit_service import AuditService
from app.utils.money import quantize_money
from app.utils.period import month_date_range

_HUNDRED = Decimal("100")


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _validate_category(self, *, user: User, category_id: int) -> str:
        category = await category_repository.get_visible_to_user(
            self._session, category_id=category_id, user_id=user.id
        )
        if category is None:
            raise NotFoundError("The requested category was not found", code="CATEGORY_NOT_FOUND")
        if category.type.value != "EXPENSE":
            raise BusinessRuleError(
                "Budgets can only be set on expense categories", code="CATEGORY_TYPE_MISMATCH"
            )
        return category.name

    async def _to_read(self, budget: Budget) -> BudgetRead:
        date_from, date_to = month_date_range(budget.period_year, budget.period_month)
        spent = await transaction_repository.sum_expense_for_category_period(
            self._session,
            user_id=budget.user_id,
            category_id=budget.category_id,
            date_from=date_from,
            date_to=date_to,
        )
        return BudgetRead(
            id=budget.id,
            category_id=budget.category_id,
            target_amount=budget.target_amount,
            currency=budget.currency,
            period_month=budget.period_month,
            period_year=budget.period_year,
            spent=spent,
            remaining=budget.target_amount - spent,
            utilization_pct=quantize_money(spent / budget.target_amount * _HUNDRED),
            is_overspent=spent > budget.target_amount,
        )

    async def create(self, *, user: User, payload: BudgetCreate) -> BudgetRead:
        await self._validate_category(user=user, category_id=payload.category_id)
        existing = await budget_repository.get_for_period(
            self._session,
            user_id=user.id,
            category_id=payload.category_id,
            period_month=payload.period_month,
            period_year=payload.period_year,
        )
        if existing is not None:
            raise ConflictError(
                "A budget for this category and period already exists",
                code="BUDGET_ALREADY_EXISTS",
            )
        budget = budget_repository.create(
            self._session,
            user_id=user.id,
            category_id=payload.category_id,
            target_amount=payload.target_amount,
            currency=payload.currency,
            period_month=payload.period_month,
            period_year=payload.period_year,
        )
        await self._session.flush()
        AuditService.record(
            self._session,
            action="BUDGET_CREATED",
            user_id=user.id,
            entity_type="budget",
            entity_id=budget.id,
            metadata={
                "category_id": payload.category_id,
                "period_month": payload.period_month,
                "period_year": payload.period_year,
                "amount": payload.target_amount,
                "currency": payload.currency,
            },
        )
        await self._session.commit()
        await self._session.refresh(budget)
        return await self._to_read(budget)

    async def _get_owned_budget(self, *, user: User, budget_id: int) -> Budget:
        budget = await budget_repository.get_owned(
            self._session, budget_id=budget_id, user_id=user.id
        )
        if budget is None:
            raise NotFoundError("The requested budget was not found", code="BUDGET_NOT_FOUND")
        return budget

    async def get_owned(self, *, user: User, budget_id: int) -> BudgetRead:
        budget = await self._get_owned_budget(user=user, budget_id=budget_id)
        return await self._to_read(budget)

    async def list_for_period(
        self, *, user: User, period_month: int, period_year: int
    ) -> list[BudgetRead]:
        budgets = await budget_repository.list_for_period(
            self._session, user_id=user.id, period_month=period_month, period_year=period_year
        )
        return [await self._to_read(budget) for budget in budgets]

    async def update(self, *, user: User, budget_id: int, payload: BudgetUpdate) -> BudgetRead:
        budget = await self._get_owned_budget(user=user, budget_id=budget_id)
        budget.target_amount = payload.target_amount
        await self._session.commit()
        await self._session.refresh(budget)
        return await self._to_read(budget)

    async def delete(self, *, user: User, budget_id: int) -> None:
        budget = await self._get_owned_budget(user=user, budget_id=budget_id)
        await budget_repository.delete(self._session, budget)
        await self._session.commit()

    async def summary(
        self, *, user: User, period_month: int, period_year: int
    ) -> BudgetSummaryResponse:
        budgets = await budget_repository.list_for_period(
            self._session, user_id=user.id, period_month=period_month, period_year=period_year
        )
        categories: list[BudgetSummaryCategory] = []
        total_budgeted = Decimal("0.00")
        total_spent = Decimal("0.00")
        for budget in budgets:
            read = await self._to_read(budget)
            category_name = await self._validate_category(user=user, category_id=budget.category_id)
            categories.append(
                BudgetSummaryCategory(
                    budget_id=budget.id,
                    category_id=budget.category_id,
                    category_name=category_name,
                    target_amount=read.target_amount,
                    spent=read.spent,
                    remaining=read.remaining,
                    utilization_pct=read.utilization_pct,
                    is_overspent=read.is_overspent,
                )
            )
            total_budgeted += read.target_amount
            total_spent += read.spent
        return BudgetSummaryResponse(
            period_month=period_month,
            period_year=period_year,
            total_budgeted=total_budgeted,
            total_spent=total_spent,
            categories=categories,
        )


def current_period() -> tuple[int, int]:
    today = datetime.datetime.now(datetime.UTC).date()
    return today.month, today.year
