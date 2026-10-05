"""Idempotent recurring-transaction processing - UC-09. See docs/architecture/data-flow.md §3
and docs/database-design.md §3.11 for the design: the UNIQUE(recurring_rule_id,
scheduled_date) constraint on recurring_occurrences is the actual source of correctness,
not application-level check-then-insert logic, which would have a race window.
"""

import datetime

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import RecurringStatus, TransactionType
from app.models.recurring_rule import RecurringRule
from app.models.transaction import Transaction
from app.repositories import (
    account_repository,
    recurring_occurrence_repository,
    recurring_rule_repository,
    transaction_repository,
)
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.recurring_math import compute_next_run_date
from app.services.transaction_service import signed_effect

logger = structlog.get_logger(__name__)


class RecurringProcessingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def process_occurrence(
        self, *, rule: RecurringRule, scheduled_date: datetime.date
    ) -> Transaction | None:
        """Materializes one due occurrence as a real transaction. Returns None (a safe,
        idempotent no-op) if this exact (rule, date) was already processed - whether this is
        the first attempt racing a concurrent one, or a retry after a prior crash.
        """
        # Fast-path check: avoids the cost of a failed INSERT in the common case. Not itself
        # the source of correctness - the DB constraint below is what actually prevents a
        # race from producing two transactions.
        existing = await recurring_occurrence_repository.get_by_rule_and_date(
            self._session, recurring_rule_id=rule.id, scheduled_date=scheduled_date
        )
        if existing is not None:
            return None

        transaction_type = TransactionType(rule.type.value)
        try:
            # SAVEPOINT, not the outer transaction: lets a batch run (multiple rules
            # processed in one worker invocation - see process_due_recurring_rules) continue
            # past one failed/already-processed rule instead of aborting everything, per
            # docs/architecture/background-jobs.md §3 ("failure of one item does not abort
            # the whole batch").
            async with self._session.begin_nested():
                account = await account_repository.get_owned_for_update(
                    self._session, account_id=rule.account_id, user_id=rule.user_id
                )
                if account is None or account.is_archived:
                    logger.warning(
                        "recurring_rule_skipped_invalid_account",
                        rule_id=rule.id,
                        account_id=rule.account_id,
                    )
                    return None

                transaction = transaction_repository.create(
                    self._session,
                    user_id=rule.user_id,
                    account_id=account.id,
                    category_id=rule.category_id,
                    type=transaction_type,
                    amount=rule.amount,
                    currency=rule.currency,
                    description=rule.description,
                    merchant=None,
                    notes=None,
                    transaction_date=scheduled_date,
                )
                account.balance += signed_effect(transaction_type, rule.amount)
                await self._session.flush()  # assigns transaction.id

                recurring_occurrence_repository.create(
                    self._session,
                    recurring_rule_id=rule.id,
                    scheduled_date=scheduled_date,
                    transaction_id=transaction.id,
                )
                # Triggers the UNIQUE(recurring_rule_id, scheduled_date) constraint check.
                # A violation here raises IntegrityError, caught below, and begin_nested()
                # rolls back everything in this block - the transaction insert and balance
                # update included - so no partial effect survives.
                await self._session.flush()
                AuditService.record(
                    self._session,
                    action="RECURRING_TRANSACTION_PROCESSED",
                    user_id=rule.user_id,
                    entity_type="recurring_rule",
                    entity_id=rule.id,
                    metadata={
                        "rule_id": rule.id,
                        "scheduled_date": scheduled_date,
                        "amount": rule.amount,
                        "currency": rule.currency,
                    },
                )
                await NotificationService(self._session).notify(
                    user_id=rule.user_id,
                    type="RECURRING_TRANSACTION_PROCESSED",
                    title="Recurring transaction posted",
                    message=f"'{rule.description}' was recorded for {scheduled_date.isoformat()}.",
                    metadata={"rule_id": rule.id},
                )
        except IntegrityError:
            logger.info(
                "recurring_occurrence_already_processed",
                rule_id=rule.id,
                scheduled_date=scheduled_date.isoformat(),
            )
            return None

        return transaction

    async def process_due_rules(
        self, *, as_of: datetime.date, catchup_limit: int
    ) -> list[Transaction]:
        """Entry point for the scheduled worker sweep. For each active, due rule, generates
        every occurrence from its current next_run_date up to `as_of` (catching up after a
        worker outage, rather than silently skipping missed rent/salary entries), bounded by
        catchup_limit as a safety valve against runaway iteration on bad data.
        """
        created: list[Transaction] = []
        rules = await recurring_rule_repository.list_due(self._session, as_of=as_of)
        for rule in rules:
            iterations = 0
            while rule.next_run_date <= as_of and iterations < catchup_limit:
                iterations += 1
                if rule.end_date is not None and rule.next_run_date > rule.end_date:
                    rule.status = RecurringStatus.ENDED
                    await self._session.commit()
                    break

                scheduled_date = rule.next_run_date
                transaction = await self.process_occurrence(
                    rule=rule, scheduled_date=scheduled_date
                )
                rule.next_run_date = compute_next_run_date(
                    scheduled_date, frequency=rule.frequency, interval=rule.interval
                )
                if rule.end_date is not None and rule.next_run_date > rule.end_date:
                    rule.status = RecurringStatus.ENDED
                await self._session.commit()

                if transaction is not None:
                    created.append(transaction)
        return created
