from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import ReportCache
from app.core.config import Settings
from app.models.enums import CategoryType, GoalStatus, TransactionType
from app.models.user import User
from app.repositories import report_repository
from app.schemas.report import (
    AccountBalanceItem,
    BalancesReport,
    BudgetsGoalsSnapshot,
    CategoryAmount,
    CategoryBreakdown,
    CategoryBreakdownItem,
    MonthlySummary,
)
from app.services.budget_service import BudgetService
from app.services.goal_service import GoalService
from app.utils.money import quantize_money
from app.utils.period import month_date_range

_HUNDRED = Decimal("100")
_TOP_CATEGORY_COUNT = 5


class ReportService:
    """Reports are derived from live transactional data. Only the two most-requested
    aggregates are cached (monthly summary, balances) - caching-strategy.md §1. Writes
    invalidate them via ReportCache.invalidate_user.
    """

    def __init__(self, session: AsyncSession, settings: Settings, cache: ReportCache) -> None:
        self._session = session
        self._settings = settings
        self._cache = cache

    async def monthly_summary(self, *, user: User, month: int, year: int) -> MonthlySummary:
        key = ReportCache.key(user.id, f"monthly:{year}-{month:02d}")
        cached = await self._cache.get(key)
        if cached is not None:
            return MonthlySummary.model_validate(cached)

        date_from, date_to = month_date_range(year, month)
        totals = await report_repository.totals_by_type(
            self._session, user_id=user.id, date_from=date_from, date_to=date_to
        )
        income = quantize_money(totals.get(TransactionType.INCOME, Decimal("0")))
        expense = quantize_money(totals.get(TransactionType.EXPENSE, Decimal("0")))
        top = await report_repository.totals_by_category(
            self._session,
            user_id=user.id,
            transaction_type=TransactionType.EXPENSE,
            date_from=date_from,
            date_to=date_to,
        )
        summary = MonthlySummary(
            period_month=month,
            period_year=year,
            total_income=income,
            total_expense=expense,
            net_savings=quantize_money(income - expense),
            top_categories=[
                CategoryAmount(category_id=cid, category_name=name, amount=quantize_money(amount))
                for cid, name, amount in top[:_TOP_CATEGORY_COUNT]
            ],
        )
        await self._cache.set(
            key, summary.model_dump(mode="json"), self._settings.report_cache_ttl_seconds
        )
        return summary

    async def category_breakdown(
        self, *, user: User, month: int, year: int, type: CategoryType
    ) -> CategoryBreakdown:
        date_from, date_to = month_date_range(year, month)
        rows = await report_repository.totals_by_category(
            self._session,
            user_id=user.id,
            transaction_type=TransactionType(type.value),
            date_from=date_from,
            date_to=date_to,
        )
        total = sum((amount for _, _, amount in rows), Decimal("0"))
        items = [
            CategoryBreakdownItem(
                category_id=cid,
                category_name=name,
                amount=quantize_money(amount),
                pct_of_total=(
                    quantize_money(amount / total * _HUNDRED) if total else Decimal("0.00")
                ),
            )
            for cid, name, amount in rows
        ]
        return CategoryBreakdown(
            period_month=month,
            period_year=year,
            type=type,
            total=quantize_money(total),
            items=items,
        )

    async def balances(self, *, user: User) -> BalancesReport:
        key = ReportCache.key(user.id, "balances")
        cached = await self._cache.get(key)
        if cached is not None:
            return BalancesReport.model_validate(cached)

        accounts = await report_repository.active_accounts(self._session, user_id=user.id)
        items = [
            AccountBalanceItem(
                account_id=a.id, name=a.name, currency=a.currency, balance=quantize_money(a.balance)
            )
            for a in accounts
        ]
        totals: dict[str, Decimal] = {}
        for item in items:
            totals[item.currency] = quantize_money(
                totals.get(item.currency, Decimal("0")) + item.balance
            )
        report = BalancesReport(accounts=items, totals_by_currency=totals)
        await self._cache.set(
            key, report.model_dump(mode="json"), self._settings.balances_cache_ttl_seconds
        )
        return report

    async def budgets_goals_snapshot(
        self, *, user: User, month: int, year: int
    ) -> BudgetsGoalsSnapshot:
        budgets = await BudgetService(self._session).list_for_period(
            user=user, period_month=month, period_year=year
        )
        goals, _ = await GoalService(self._session).list_for_user(
            user=user, status=GoalStatus.ACTIVE, page=1, page_size=100
        )
        return BudgetsGoalsSnapshot(
            period_month=month, period_year=year, budgets=budgets, goals=goals
        )
