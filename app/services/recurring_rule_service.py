from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.account import Account
from app.models.enums import RecurringStatus
from app.models.recurring_rule import RecurringRule
from app.models.user import User
from app.repositories import account_repository, category_repository, recurring_rule_repository
from app.schemas.recurring import RecurringRuleCreate, RecurringRuleUpdate


class RecurringRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _validate_account(self, *, user: User, account_id: int) -> Account:
        account = await account_repository.get_owned(
            self._session, account_id=account_id, user_id=user.id
        )
        if account is None:
            raise NotFoundError("The requested account was not found", code="ACCOUNT_NOT_FOUND")
        if account.is_archived:
            raise BusinessRuleError(
                "This account is archived and cannot be used for new rules",
                code="ACCOUNT_ARCHIVED",
            )
        return account

    async def _validate_category(self, *, user: User, category_id: int, expected_type: str) -> None:
        category = await category_repository.get_visible_to_user(
            self._session, category_id=category_id, user_id=user.id
        )
        if category is None:
            raise NotFoundError("The requested category was not found", code="CATEGORY_NOT_FOUND")
        if category.type.value != expected_type:
            raise BusinessRuleError(
                "This category cannot be used with this rule's type",
                code="CATEGORY_TYPE_MISMATCH",
            )

    async def create(self, *, user: User, payload: RecurringRuleCreate) -> RecurringRule:
        await self._validate_account(user=user, account_id=payload.account_id)
        if payload.category_id is not None:
            await self._validate_category(
                user=user, category_id=payload.category_id, expected_type=payload.type.value
            )
        rule = recurring_rule_repository.create(
            self._session,
            user_id=user.id,
            account_id=payload.account_id,
            category_id=payload.category_id,
            type=payload.type,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            frequency=payload.frequency,
            interval=payload.interval,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )
        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def _get_owned_rule(self, *, user: User, rule_id: int) -> RecurringRule:
        rule = await recurring_rule_repository.get_owned(
            self._session, rule_id=rule_id, user_id=user.id
        )
        if rule is None:
            raise NotFoundError(
                "The requested recurring rule was not found", code="RECURRING_RULE_NOT_FOUND"
            )
        return rule

    async def get_owned(self, *, user: User, rule_id: int) -> RecurringRule:
        return await self._get_owned_rule(user=user, rule_id=rule_id)

    async def list_for_user(
        self, *, user: User, status: RecurringStatus | None
    ) -> list[RecurringRule]:
        return await recurring_rule_repository.list_for_user(
            self._session, user_id=user.id, status=status
        )

    async def update(
        self, *, user: User, rule_id: int, payload: RecurringRuleUpdate
    ) -> RecurringRule:
        rule = await self._get_owned_rule(user=user, rule_id=rule_id)
        if payload.category_id is not None:
            await self._validate_category(
                user=user, category_id=payload.category_id, expected_type=rule.type.value
            )
            rule.category_id = payload.category_id
        if payload.amount is not None:
            rule.amount = payload.amount
        if payload.description is not None:
            rule.description = payload.description
        if payload.end_date is not None:
            rule.end_date = payload.end_date
        # Changing frequency/interval/start_date recalculates next_run_date going forward
        # but never retroactively alters already-generated transactions - docs/api-design.md §10.
        schedule_changed = False
        if payload.frequency is not None:
            rule.frequency = payload.frequency
            schedule_changed = True
        if payload.interval is not None:
            rule.interval = payload.interval
            schedule_changed = True
        if payload.start_date is not None:
            rule.start_date = payload.start_date
            schedule_changed = True
        if schedule_changed:
            rule.next_run_date = max(rule.next_run_date, rule.start_date)
        await self._session.commit()
        await self._session.refresh(rule)
        return rule

    async def pause(self, *, user: User, rule_id: int) -> None:
        rule = await self._get_owned_rule(user=user, rule_id=rule_id)
        if rule.status == RecurringStatus.ENDED:
            raise BusinessRuleError("An ended rule cannot be paused", code="RECURRING_RULE_ENDED")
        rule.status = RecurringStatus.PAUSED
        await self._session.commit()

    async def resume(self, *, user: User, rule_id: int) -> None:
        rule = await self._get_owned_rule(user=user, rule_id=rule_id)
        if rule.status == RecurringStatus.ENDED:
            raise BusinessRuleError("An ended rule cannot be resumed", code="RECURRING_RULE_ENDED")
        rule.status = RecurringStatus.ACTIVE
        await self._session.commit()

    async def delete(self, *, user: User, rule_id: int) -> None:
        """Soft-delete: ENDED, not a hard delete - generated transactions/occurrences must
        remain untouched (FR-RECUR-04).
        """
        rule = await self._get_owned_rule(user=user, rule_id=rule_id)
        rule.status = RecurringStatus.ENDED
        await self._session.commit()
