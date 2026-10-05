from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.budget import (
    BudgetCreate,
    BudgetRead,
    BudgetSummaryResponse,
    BudgetUpdate,
)
from app.services.budget_service import BudgetService, current_period

router = APIRouter(prefix="/budgets", tags=["Budgets"])


def get_budget_service(session: AsyncSession = Depends(get_db_session)) -> BudgetService:
    return BudgetService(session)


@router.post("", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
async def create_budget(
    payload: BudgetCreate,
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> BudgetRead:
    return await budget_service.create(user=current_user, payload=payload)


@router.get("", response_model=list[BudgetRead])
async def list_budgets(
    period_month: int | None = Query(default=None, ge=1, le=12),
    period_year: int | None = Query(default=None, ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> list[BudgetRead]:
    month, year = _resolve_period(period_month, period_year)
    return await budget_service.list_for_period(
        user=current_user, period_month=month, period_year=year
    )


# Registered before "/{budget_id}" - Starlette matches path templates in registration
# order and {budget_id} would otherwise swallow "summary" as its (int-conversion-failing)
# value, since route matching doesn't consider the parameter's type annotation.
@router.get("/summary", response_model=BudgetSummaryResponse)
async def get_budget_summary(
    period_month: int | None = Query(default=None, ge=1, le=12),
    period_year: int | None = Query(default=None, ge=2000, le=2100),
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> BudgetSummaryResponse:
    month, year = _resolve_period(period_month, period_year)
    return await budget_service.summary(user=current_user, period_month=month, period_year=year)


@router.get("/{budget_id}", response_model=BudgetRead)
async def get_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> BudgetRead:
    return await budget_service.get_owned(user=current_user, budget_id=budget_id)


@router.patch("/{budget_id}", response_model=BudgetRead)
async def update_budget(
    budget_id: int,
    payload: BudgetUpdate,
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> BudgetRead:
    return await budget_service.update(user=current_user, budget_id=budget_id, payload=payload)


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    budget_id: int,
    current_user: User = Depends(get_current_user),
    budget_service: BudgetService = Depends(get_budget_service),
) -> None:
    await budget_service.delete(user=current_user, budget_id=budget_id)


def _resolve_period(period_month: int | None, period_year: int | None) -> tuple[int, int]:
    default_month, default_year = current_period()
    return period_month or default_month, period_year or default_year
