from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db_session
from app.models.enums import RecurringStatus
from app.models.recurring_rule import RecurringRule
from app.models.user import User
from app.repositories import recurring_occurrence_repository
from app.schemas.recurring import (
    RecurringOccurrenceRead,
    RecurringRuleCreate,
    RecurringRuleRead,
    RecurringRuleUpdate,
    UpcomingOccurrence,
)
from app.services.recurring_math import compute_next_run_date
from app.services.recurring_rule_service import RecurringRuleService

router = APIRouter(prefix="/recurring-transactions", tags=["Recurring Transactions"])

UPCOMING_OCCURRENCE_COUNT = 5


def get_recurring_rule_service(
    session: AsyncSession = Depends(get_db_session),
) -> RecurringRuleService:
    return RecurringRuleService(session)


@router.post("", response_model=RecurringRuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RecurringRuleCreate,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> RecurringRule:
    return await rule_service.create(user=current_user, payload=payload)


@router.get("", response_model=list[RecurringRuleRead])
async def list_rules(
    status: RecurringStatus | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> list[RecurringRule]:
    return await rule_service.list_for_user(user=current_user, status=status)


@router.get("/{rule_id}", response_model=RecurringRuleRead)
async def get_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> RecurringRule:
    return await rule_service.get_owned(user=current_user, rule_id=rule_id)


@router.patch("/{rule_id}", response_model=RecurringRuleRead)
async def update_rule(
    rule_id: int,
    payload: RecurringRuleUpdate,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> RecurringRule:
    return await rule_service.update(user=current_user, rule_id=rule_id, payload=payload)


@router.post("/{rule_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> None:
    await rule_service.pause(user=current_user, rule_id=rule_id)


@router.post("/{rule_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> None:
    await rule_service.resume(user=current_user, rule_id=rule_id)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
) -> None:
    await rule_service.delete(user=current_user, rule_id=rule_id)


@router.get("/{rule_id}/occurrences")
async def list_occurrences(
    rule_id: int,
    upcoming: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    rule_service: RecurringRuleService = Depends(get_recurring_rule_service),
    session: AsyncSession = Depends(get_db_session),
) -> list[UpcomingOccurrence] | list[RecurringOccurrenceRead]:
    rule = await rule_service.get_owned(user=current_user, rule_id=rule_id)
    if upcoming:
        dates: list[UpcomingOccurrence] = []
        next_date = rule.next_run_date
        for _ in range(UPCOMING_OCCURRENCE_COUNT):
            dates.append(UpcomingOccurrence(scheduled_date=next_date))
            next_date = compute_next_run_date(
                next_date, frequency=rule.frequency, interval=rule.interval
            )
            if rule.end_date is not None and next_date > rule.end_date:
                break
        return dates

    occurrences = await recurring_occurrence_repository.list_for_rule(
        session, recurring_rule_id=rule.id
    )
    return [RecurringOccurrenceRead.model_validate(o, from_attributes=True) for o in occurrences]
