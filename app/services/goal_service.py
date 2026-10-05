import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.enums import GoalStatus
from app.models.goal import Goal
from app.models.goal_contribution import GoalContribution
from app.models.user import User
from app.repositories import (
    account_repository,
    goal_contribution_repository,
    goal_repository,
    transaction_repository,
)
from app.schemas.goal import GoalContributionCreate, GoalCreate, GoalRead, GoalUpdate
from app.services.audit_service import AuditService
from app.services.goal_math import compute_goal_progress
from app.services.notification_service import NotificationService


def _today() -> datetime.date:
    return datetime.datetime.now(datetime.UTC).date()


def _achieved_status(*, current_amount: Decimal, target_amount: Decimal) -> GoalStatus:
    return GoalStatus.ACHIEVED if current_amount >= target_amount else GoalStatus.ACTIVE


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _to_read(self, goal: Goal) -> GoalRead:
        progress = compute_goal_progress(
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            target_date=goal.target_date,
            today=_today(),
        )
        return GoalRead(
            id=goal.id,
            name=goal.name,
            target_amount=goal.target_amount,
            current_amount=goal.current_amount,
            currency=goal.currency,
            target_date=goal.target_date,
            status=goal.status,
            progress_pct=progress.progress_pct,
            remaining_amount=progress.remaining_amount,
            required_monthly_contribution=progress.required_monthly_contribution,
            is_achieved=progress.is_achieved,
            is_overdue=progress.is_overdue,
        )

    async def create(self, *, user: User, payload: GoalCreate) -> GoalRead:
        status = _achieved_status(
            current_amount=payload.current_amount, target_amount=payload.target_amount
        )
        goal = goal_repository.create(
            self._session,
            user_id=user.id,
            name=payload.name,
            target_amount=payload.target_amount,
            current_amount=payload.current_amount,
            currency=payload.currency,
            target_date=payload.target_date,
            status=status,
        )
        await self._session.flush()
        AuditService.record(
            self._session,
            action="GOAL_CREATED",
            user_id=user.id,
            entity_type="goal",
            entity_id=goal.id,
            metadata={"amount": payload.target_amount, "currency": payload.currency},
        )
        if status == GoalStatus.ACHIEVED:
            await NotificationService(self._session).notify(
                user_id=user.id,
                type="GOAL_ACHIEVED",
                title="Goal achieved",
                message=f"You reached your goal '{goal.name}'.",
                metadata={"goal_id": goal.id},
            )
        await self._session.commit()
        await self._session.refresh(goal)
        return self._to_read(goal)

    async def _get_owned_goal(self, *, user: User, goal_id: int) -> Goal:
        goal = await goal_repository.get_owned(self._session, goal_id=goal_id, user_id=user.id)
        if goal is None:
            raise NotFoundError("The requested goal was not found", code="GOAL_NOT_FOUND")
        return goal

    async def get_owned(self, *, user: User, goal_id: int) -> GoalRead:
        goal = await self._get_owned_goal(user=user, goal_id=goal_id)
        return self._to_read(goal)

    async def list_for_user(
        self, *, user: User, status: GoalStatus | None, page: int, page_size: int
    ) -> tuple[list[GoalRead], int]:
        goals, total = await goal_repository.list_for_user(
            self._session, user_id=user.id, status=status, page=page, page_size=page_size
        )
        return [self._to_read(goal) for goal in goals], total

    async def update(self, *, user: User, goal_id: int, payload: GoalUpdate) -> GoalRead:
        goal = await self._get_owned_goal(user=user, goal_id=goal_id)
        if goal.status == GoalStatus.CLOSED:
            raise BusinessRuleError("A closed goal cannot be edited", code="GOAL_CLOSED")
        if payload.name is not None:
            goal.name = payload.name
        if payload.target_amount is not None:
            goal.target_amount = payload.target_amount
        if payload.target_date is not None:
            goal.target_date = payload.target_date
        if payload.target_amount is not None and goal.status != GoalStatus.ACHIEVED:
            goal.status = _achieved_status(
                current_amount=goal.current_amount, target_amount=goal.target_amount
            )
        await self._session.commit()
        await self._session.refresh(goal)
        return self._to_read(goal)

    async def add_contribution(
        self, *, user: User, goal_id: int, payload: GoalContributionCreate
    ) -> GoalContribution:
        goal = await self._get_owned_goal(user=user, goal_id=goal_id)
        if goal.status == GoalStatus.CLOSED:
            raise BusinessRuleError("Cannot contribute to a closed goal", code="GOAL_CLOSED")
        if payload.source_account_id is not None:
            account = await account_repository.get_owned(
                self._session, account_id=payload.source_account_id, user_id=user.id
            )
            if account is None:
                raise NotFoundError("The requested account was not found", code="ACCOUNT_NOT_FOUND")
        if payload.source_transaction_id is not None:
            transaction = await transaction_repository.get_owned(
                self._session, transaction_id=payload.source_transaction_id, user_id=user.id
            )
            if transaction is None:
                raise NotFoundError(
                    "The requested transaction was not found", code="TRANSACTION_NOT_FOUND"
                )

        contribution = goal_contribution_repository.create(
            self._session,
            goal_id=goal.id,
            amount=payload.amount,
            contributed_at=payload.contributed_at,
            source_account_id=payload.source_account_id,
            source_transaction_id=payload.source_transaction_id,
        )
        was_achieved = goal.status == GoalStatus.ACHIEVED
        goal.current_amount += payload.amount
        goal.status = _achieved_status(
            current_amount=goal.current_amount, target_amount=goal.target_amount
        )
        if goal.status == GoalStatus.ACHIEVED and not was_achieved:
            await NotificationService(self._session).notify(
                user_id=user.id,
                type="GOAL_ACHIEVED",
                title="Goal achieved",
                message=f"You reached your goal '{goal.name}'.",
                metadata={"goal_id": goal.id},
            )
        await self._session.commit()
        await self._session.refresh(contribution)
        return contribution

    async def list_contributions(
        self, *, user: User, goal_id: int, page: int, page_size: int
    ) -> tuple[list[GoalContribution], int]:
        await self._get_owned_goal(user=user, goal_id=goal_id)  # ownership check
        return await goal_contribution_repository.list_for_goal(
            self._session, goal_id=goal_id, page=page, page_size=page_size
        )

    async def close(self, *, user: User, goal_id: int) -> None:
        goal = await self._get_owned_goal(user=user, goal_id=goal_id)
        if goal.status == GoalStatus.CLOSED:
            return  # idempotent
        goal.status = GoalStatus.CLOSED
        await self._session.commit()
