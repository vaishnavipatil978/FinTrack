"""UC-07 alternate flow 4b: concurrent transfers touching the same account must serialize
on its row lock, never lose an update. This needs genuinely separate DB connections racing
for real (not the shared rolled-back session the rest of the suite uses), so each concurrent
transfer below opens its own connection/session and actually commits - the test cleans up
its own rows afterward instead of relying on fixture rollback. See docs/05-use-cases.md UC-07
and docs/architecture/data-flow.md §2.
"""

import asyncio
import datetime
from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.enums import AccountType
from app.models.notification import Notification, NotificationPreference
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User
from app.repositories import user_repository
from app.schemas.account import AccountCreate
from app.schemas.transfer import TransferCreate
from app.services.account_service import AccountService
from app.services.auth_service import AuthService
from app.services.transfer_service import TransferService

CONCURRENT_TRANSFERS = 10
TRANSFER_AMOUNT = Decimal("50.00")
STARTING_BALANCE = Decimal("10000.00")


async def _run_one_transfer(
    database_url: str, *, user_id: int, from_account_id: int, to_account_id: int
) -> None:
    """Opens its own connection/session - simulating one independent HTTP request - so its
    row lock on the source account is a real, separate-connection Postgres lock, not just
    a no-op within one already-open transaction.
    """
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            session = AsyncSession(bind=connection, expire_on_commit=False)
            user = await user_repository.get_by_id(session, user_id)
            assert user is not None
            await TransferService(session).create(
                user=user,
                payload=TransferCreate(
                    from_account_id=from_account_id,
                    to_account_id=to_account_id,
                    amount=TRANSFER_AMOUNT,
                    currency="INR",
                    transfer_date=datetime.date(2026, 9, 1),
                ),
            )
    finally:
        await engine.dispose()


async def test_concurrent_transfers_from_the_same_account_never_lose_an_update(
    db_settings: Settings,
) -> None:
    setup_engine = create_async_engine(db_settings.database_url, poolclass=NullPool)
    user_id: int | None = None
    source_id: int | None = None
    dest_ids: list[int] = []
    try:
        async with setup_engine.connect() as connection:
            session = AsyncSession(bind=connection, expire_on_commit=False)
            auth_service = AuthService(session, db_settings)
            user = await auth_service.register(
                email="concurrency@example.com",
                password="correct-horse-battery-staple",
                full_name="Concurrency Test",
            )
            user_id = user.id

            account_service = AccountService(session)
            source = await account_service.create(
                user=user,
                payload=AccountCreate(
                    name="Source",
                    type=AccountType.BANK,
                    currency="INR",
                    opening_balance=STARTING_BALANCE,
                ),
            )
            source_id = source.id
            for i in range(CONCURRENT_TRANSFERS):
                dest = await account_service.create(
                    user=user,
                    payload=AccountCreate(
                        name=f"Dest {i}",
                        type=AccountType.BANK,
                        currency="INR",
                        opening_balance=Decimal("0.00"),
                    ),
                )
                dest_ids.append(dest.id)

        # The real race: CONCURRENT_TRANSFERS independent connections, all debiting the
        # SAME source account at once.
        await asyncio.gather(
            *[
                _run_one_transfer(
                    db_settings.database_url,
                    user_id=user_id,
                    from_account_id=source_id,
                    to_account_id=dest_id,
                )
                for dest_id in dest_ids
            ]
        )

        async with setup_engine.connect() as connection:
            session = AsyncSession(bind=connection, expire_on_commit=False)
            refreshed_user = await user_repository.get_by_id(session, user_id)
            assert refreshed_user is not None
            account_service = AccountService(session)
            final_source = await account_service.get_owned(
                user=refreshed_user, account_id=source_id
            )
            expected = STARTING_BALANCE - (TRANSFER_AMOUNT * CONCURRENT_TRANSFERS)
            assert final_source.balance == expected, (
                f"lost update detected: expected {expected}, got {final_source.balance} "
                f"(if this is higher than expected, two concurrent transfers both read the "
                f"pre-transfer balance and one debit was overwritten by the other)"
            )

            total_dest_balance = Decimal("0.00")
            for dest_id in dest_ids:
                dest_account = await account_service.get_owned(
                    user=refreshed_user, account_id=dest_id
                )
                total_dest_balance += dest_account.balance
            assert total_dest_balance == TRANSFER_AMOUNT * CONCURRENT_TRANSFERS
    finally:
        async with setup_engine.connect() as connection:
            all_account_ids = [source_id, *dest_ids] if source_id is not None else []
            if all_account_ids:
                await connection.execute(
                    delete(Transaction).where(Transaction.account_id.in_(all_account_ids))
                )
            if user_id is not None:
                # Transfer rows reference accounts (from/to) - must go before Account rows.
                await connection.execute(delete(Transfer).where(Transfer.user_id == user_id))
            if all_account_ids:
                await connection.execute(delete(Account).where(Account.id.in_(all_account_ids)))
            if user_id is not None:
                # Audit/notification rows reference the user; the app never deletes them, so
                # this test-only cleanup is the one place they are removed.
                await connection.execute(delete(AuditLog).where(AuditLog.user_id == user_id))
                await connection.execute(
                    delete(Notification).where(Notification.user_id == user_id)
                )
                await connection.execute(
                    delete(NotificationPreference).where(NotificationPreference.user_id == user_id)
                )
                await connection.execute(delete(User).where(User.id == user_id))
            await connection.commit()
        await setup_engine.dispose()
