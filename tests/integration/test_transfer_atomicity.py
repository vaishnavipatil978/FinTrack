"""UC-07's two hardest correctness guarantees: a mid-transfer failure must leave BOTH
accounts completely untouched (this file), and two concurrent transfers against the same
account must never lose an update (test_transfer_concurrency.py). See
docs/05-use-cases.md UC-07 and docs/architecture/data-flow.md §2.
"""

import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import AccountType
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories import transaction_repository as real_transaction_repository
from app.repositories import user_repository
from app.schemas.account import AccountCreate
from app.schemas.transfer import TransferCreate
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.services.transfer_service import TransferService


async def _create_test_user(session: AsyncSession, settings: Settings, *, email: str) -> User:
    auth_service = AuthService(session, settings)
    return await auth_service.register(
        email=email, password="correct-horse-battery-staple", full_name="Test"
    )


async def test_forced_failure_between_legs_leaves_both_balances_unchanged(
    db_session: AsyncSession, db_settings: Settings
) -> None:
    user = await _create_test_user(db_session, db_settings, email="atomicity@example.com")
    account_service = AccountService(db_session)
    src = await account_service.create(
        user=user,
        payload=AccountCreate(
            name="Source", type=AccountType.BANK, currency="INR", opening_balance=Decimal("1000.00")
        ),
    )
    dst = await account_service.create(
        user=user,
        payload=AccountCreate(
            name="Dest", type=AccountType.BANK, currency="INR", opening_balance=Decimal("0.00")
        ),
    )

    call_count = 0

    def flaky_create(*args: Any, **kwargs: Any) -> Transaction:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            # Simulates a crash/DB error after the source leg (transaction row + debit)
            # has been applied to the session, but before the destination leg is created -
            # UC-07 alternate flow 4a's exact failure point.
            raise RuntimeError("simulated failure between transfer legs")
        return real_transaction_repository.create(*args, **kwargs)

    # Captured before the rollback below expires these ORM objects - accessing an expired
    # attribute via plain Python attribute access (not an awaited SQLAlchemy call) breaks
    # the async greenlet bridge (MissingGreenlet).
    src_id, dst_id, user_id = src.id, dst.id, user.id

    transfer_service = TransferService(db_session)
    create_target = "app.services.transfer_service.transaction_repository.create"
    with patch(create_target, side_effect=flaky_create):
        with pytest.raises(RuntimeError, match="simulated failure between transfer legs"):
            await transfer_service.create(
                user=user,
                payload=TransferCreate(
                    from_account_id=src_id,
                    to_account_id=dst_id,
                    amount=Decimal("300.00"),
                    currency="INR",
                    transfer_date=datetime.date(2026, 9, 1),
                ),
            )

    assert call_count == 2  # confirms the injected failure actually fired mid-sequence

    # Reproduces what get_db_session's context manager does on an unhandled exception in
    # production: roll back whatever the failed request left pending, before observing state.
    await db_session.rollback()

    # Re-fetched fresh (not the pre-rollback `user`/`src`/`dst` objects, now expired) via an
    # awaited call, staying inside SQLAlchemy's async greenlet bridge throughout.
    refreshed_user = await user_repository.get_by_id(db_session, user_id)
    assert refreshed_user is not None
    refreshed_src = await account_service.get_owned(user=refreshed_user, account_id=src_id)
    refreshed_dst = await account_service.get_owned(user=refreshed_user, account_id=dst_id)
    assert refreshed_src.balance == Decimal("1000.00")
    assert refreshed_dst.balance == Decimal("0.00")

    # And no transfer row survived either - fully atomic, not just balances.
    _transfers, total = await transfer_service.list_for_user(
        user=refreshed_user, account_id=None, date_from=None, date_to=None, page=1, page_size=20
    )
    assert total == 0
