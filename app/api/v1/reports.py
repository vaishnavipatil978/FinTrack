from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_user, get_report_cache
from app.core.cache import ReportCache
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.enums import CategoryType
from app.models.user import User
from app.schemas.report import (
    BalancesReport,
    BudgetsGoalsSnapshot,
    CategoryBreakdown,
    MonthlySummary,
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])


def get_report_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
    cache: ReportCache = Depends(get_report_cache),
) -> ReportService:
    return ReportService(session, settings, cache)


@router.get("/monthly-summary", response_model=MonthlySummary)
async def monthly_summary(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> MonthlySummary:
    return await service.monthly_summary(user=current_user, month=month, year=year)


@router.get("/category-breakdown", response_model=CategoryBreakdown)
async def category_breakdown(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    type: CategoryType = Query(default=CategoryType.EXPENSE),
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> CategoryBreakdown:
    return await service.category_breakdown(user=current_user, month=month, year=year, type=type)


@router.get("/balances", response_model=BalancesReport)
async def balances(
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> BalancesReport:
    return await service.balances(user=current_user)


@router.get("/budgets-goals-snapshot", response_model=BudgetsGoalsSnapshot)
async def budgets_goals_snapshot(
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
) -> BudgetsGoalsSnapshot:
    return await service.budgets_goals_snapshot(user=current_user, month=month, year=year)
