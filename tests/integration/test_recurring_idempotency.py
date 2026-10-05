"""UC-09's correctness guarantee: processing the same (recurring_rule_id, scheduled_date)
occurrence more than once - whether from a genuine retry, a worker redelivery, or a crash
between the transaction insert and the occurrence insert - must never create more than one
transaction. See docs/05-use-cases.md UC-09 and docs/architecture/data-flow.md §3.
"""

import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import AccountType, CategoryType, RecurringFrequency
from app.models.recurring_occurrence import RecurringOccurrence
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.account import AccountCreate
from app.schemas.recurring import RecurringRuleCreate
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.services.recurring_processing_service import RecurringProcessingService
from app.services.recurring_rule_service import RecurringRuleService

SCHEDULED_DATE = datetime.date(2026, 9, 5)


async def _setup_rule(session: AsyncSession, settings: Settings) -> tuple[User, int]:
    auth_service = AuthService(session, settings)
    user = await auth_service.register(
        email="idempotency@example.com", password="correct-horse-battery-staple", full_name="Test"
    )
    account_service = AccountService(session)
    account = await account_service.create(
        user=user,
        payload=AccountCreate(
            name="Bank", type=AccountType.BANK, currency="INR", opening_balance=Decimal("100000.00")
        ),
    )
    rule_service = RecurringRuleService(session)
    rule = await rule_service.create(
        user=user,
        payload=RecurringRuleCreate(
            account_id=account.id,
            category_id=None,
            type=CategoryType.EXPENSE,
            amount=Decimal("25000.00"),
            currency="INR",
            description="Rent",
            frequency=RecurringFrequency.MONTHLY,
            interval=1,
            start_date=SCHEDULED_DATE,
            end_date=None,
        ),
    )
    return user, rule.id


async def _count_transactions_and_occurrences(
    session: AsyncSession, *, rule_id: int
) -> tuple[int, int]:
    occurrences = (
        (
            await session.execute(
                select(RecurringOccurrence).where(RecurringOccurrence.recurring_rule_id == rule_id)
            )
        )
        .scalars()
        .all()
    )
    transaction_ids = [o.transaction_id for o in occurrences]
    if not transaction_ids:
        return 0, 0
    transactions = (
        (await session.execute(select(Transaction).where(Transaction.id.in_(transaction_ids))))
        .scalars()
        .all()
    )
    return len(transactions), len(occurrences)


async def test_double_invoking_the_same_occurrence_creates_only_one_transaction(
    db_session: AsyncSession, db_settings: Settings
) -> None:
    user, rule_id = await _setup_rule(db_session, db_settings)
    processing_service = RecurringProcessingService(db_session)
    rule_service = RecurringRuleService(db_session)
    rule = await rule_service.get_owned(user=user, rule_id=rule_id)

    first = await processing_service.process_occurrence(rule=rule, scheduled_date=SCHEDULED_DATE)
    second = await processing_service.process_occurrence(rule=rule, scheduled_date=SCHEDULED_DATE)

    assert first is not None
    assert second is None  # idempotent no-op on the second call

    txn_count, occ_count = await _count_transactions_and_occurrences(db_session, rule_id=rule_id)
    assert txn_count == 1
    assert occ_count == 1

    refreshed_account = await AccountService(db_session).get_owned(
        user=user, account_id=rule.account_id
    )
    # Exactly one ₹25,000 debit applied, not two.
    assert refreshed_account.balance == Decimal("75000.00")


async def test_crash_mid_processing_leaves_no_orphaned_transaction(
    db_session: AsyncSession, db_settings: Settings
) -> None:
    user, rule_id = await _setup_rule(db_session, db_settings)
    processing_service = RecurringProcessingService(db_session)
    rule_service = RecurringRuleService(db_session)
    rule = await rule_service.get_owned(user=user, rule_id=rule_id)

    def flaky_create(*args: Any, **kwargs: Any) -> RecurringOccurrence:
        raise RuntimeError("simulated crash before the occurrence row commits")

    target = "app.services.recurring_processing_service.recurring_occurrence_repository.create"
    with patch(target, side_effect=flaky_create):
        with pytest.raises(RuntimeError, match="simulated crash"):
            await processing_service.process_occurrence(rule=rule, scheduled_date=SCHEDULED_DATE)

    # The failed attempt's SAVEPOINT must have rolled back the transaction insert + balance
    # update along with the occurrence insert - nothing survives a non-IntegrityError crash.
    txn_count, occ_count = await _count_transactions_and_occurrences(db_session, rule_id=rule_id)
    assert txn_count == 0
    assert occ_count == 0
    refreshed_account = await AccountService(db_session).get_owned(
        user=user, account_id=rule.account_id
    )
    assert refreshed_account.balance == Decimal("100000.00")

    # The retry (no mock this time) succeeds cleanly and produces exactly one transaction.
    retried = await processing_service.process_occurrence(rule=rule, scheduled_date=SCHEDULED_DATE)
    assert retried is not None
    txn_count, occ_count = await _count_transactions_and_occurrences(db_session, rule_id=rule_id)
    assert txn_count == 1
    assert occ_count == 1


async def test_process_due_rules_catches_up_on_missed_occurrences(
    db_session: AsyncSession, db_settings: Settings
) -> None:
    user, rule_id = await _setup_rule(db_session, db_settings)
    processing_service = RecurringProcessingService(db_session)
    rule = await RecurringRuleService(db_session).get_owned(user=user, rule_id=rule_id)

    # Worker hasn't run for 3 months - "today" is 3 periods past the rule's next_run_date.
    as_of = datetime.date(2026, 12, 5)
    created = await processing_service.process_due_rules(as_of=as_of, catchup_limit=366)

    assert len(created) == 4  # Sep, Oct, Nov, Dec

    txn_count, occ_count = await _count_transactions_and_occurrences(db_session, rule_id=rule_id)
    assert txn_count == 4
    assert occ_count == 4

    refreshed_account = await AccountService(db_session).get_owned(
        user=user, account_id=rule.account_id
    )
    assert refreshed_account.balance == Decimal("0.00")  # 100000 - 4*25000


async def test_process_due_rules_is_idempotent_across_repeated_sweeps(
    db_session: AsyncSession, db_settings: Settings
) -> None:
    """The worker-level entry point, invoked twice for the same due date - simulating Celery
    Beat firing the task again (e.g. after a redelivery) - must not duplicate anything.
    """
    user, rule_id = await _setup_rule(db_session, db_settings)
    processing_service = RecurringProcessingService(db_session)

    as_of = SCHEDULED_DATE
    first_run = await processing_service.process_due_rules(as_of=as_of, catchup_limit=366)
    second_run = await processing_service.process_due_rules(as_of=as_of, catchup_limit=366)

    assert len(first_run) == 1
    assert len(second_run) == 0  # nothing left due - already processed

    txn_count, occ_count = await _count_transactions_and_occurrences(db_session, rule_id=rule_id)
    assert txn_count == 1
    assert occ_count == 1
