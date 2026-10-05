from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.enums import GoalStatus
from app.models.goal_contribution import GoalContribution
from app.models.user import User
from app.schemas.goal import (
    GoalContributionCreate,
    GoalContributionListResponse,
    GoalContributionRead,
    GoalCreate,
    GoalListResponse,
    GoalRead,
    GoalUpdate,
)
from app.schemas.pagination import total_pages
from app.services.goal_service import GoalService

router = APIRouter(prefix="/goals", tags=["Goals"])


def get_goal_service(session: AsyncSession = Depends(get_db_session)) -> GoalService:
    return GoalService(session)


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
async def create_goal(
    payload: GoalCreate,
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalRead:
    return await goal_service.create(user=current_user, payload=payload)


@router.get("", response_model=GoalListResponse)
async def list_goals(
    status: GoalStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalListResponse:
    items, total = await goal_service.list_for_user(
        user=current_user, status=status, page=page, page_size=page_size
    )
    return GoalListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.get("/{goal_id}", response_model=GoalRead)
async def get_goal(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalRead:
    return await goal_service.get_owned(user=current_user, goal_id=goal_id)


@router.patch("/{goal_id}", response_model=GoalRead)
async def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalRead:
    return await goal_service.update(user=current_user, goal_id=goal_id, payload=payload)


@router.post(
    "/{goal_id}/contributions",
    response_model=GoalContributionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_contribution(
    goal_id: int,
    payload: GoalContributionCreate,
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalContribution:
    return await goal_service.add_contribution(user=current_user, goal_id=goal_id, payload=payload)


@router.get("/{goal_id}/contributions", response_model=GoalContributionListResponse)
async def list_contributions(
    goal_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> GoalContributionListResponse:
    items, total = await goal_service.list_contributions(
        user=current_user, goal_id=goal_id, page=page, page_size=page_size
    )
    return GoalContributionListResponse(
        items=[GoalContributionRead.model_validate(item, from_attributes=True) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.post("/{goal_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_goal(
    goal_id: int,
    current_user: User = Depends(get_current_user),
    goal_service: GoalService = Depends(get_goal_service),
) -> None:
    await goal_service.close(user=current_user, goal_id=goal_id)
