import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError, UnprocessableEntityError
from app.models.enums import TransactionType
from app.models.transfer import Transfer
from app.models.user import User
from app.repositories import account_repository, transaction_repository, transfer_repository
from app.schemas.transfer import TransferCreate
from app.services.audit_service import AuditService


class TransferService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user: User, payload: TransferCreate) -> Transfer:
        if payload.from_account_id == payload.to_account_id:
            raise UnprocessableEntityError(
                "A transfer must be between two different accounts",
                code="SAME_ACCOUNT_TRANSFER",
            )

        # Locks both accounts in one query, ordered ascending by id regardless of which is
        # "from"/"to" - see account_repository.lock_owned_accounts and
        # docs/architecture/data-flow.md §2 for why this ordering matters (deadlock
        # prevention between two opposite-direction concurrent transfers).
        accounts = await account_repository.lock_owned_accounts(
            self._session,
            account_ids=[payload.from_account_id, payload.to_account_id],
            user_id=user.id,
        )
        from_account = accounts.get(payload.from_account_id)
        to_account = accounts.get(payload.to_account_id)
        if from_account is None or to_account is None:
            raise NotFoundError("The requested account was not found", code="ACCOUNT_NOT_FOUND")

        if from_account.is_archived or to_account.is_archived:
            raise BusinessRuleError(
                "Archived accounts cannot participate in a transfer", code="ACCOUNT_ARCHIVED"
            )
        if from_account.currency != to_account.currency:
            raise BusinessRuleError(
                "Both accounts must share the same currency", code="CURRENCY_MISMATCH"
            )
        if from_account.currency != payload.currency:
            raise BusinessRuleError(
                "Transfer currency must match both accounts' currency",
                code="CURRENCY_MISMATCH",
            )
        if not from_account.allow_negative_balance and from_account.balance < payload.amount:
            raise BusinessRuleError(
                "The source account does not have sufficient balance",
                code="INSUFFICIENT_FUNDS",
            )

        transfer = transfer_repository.create(
            self._session,
            user_id=user.id,
            from_account_id=from_account.id,
            to_account_id=to_account.id,
            amount=payload.amount,
            currency=payload.currency,
            transfer_date=payload.transfer_date,
            description=payload.description,
        )
        # Flush so transfer.id is assigned before the two legs reference it.
        await self._session.flush()

        description = payload.description or "Transfer"
        # Each leg's transaction row and balance update are paired together, so a failure
        # injected between the two transaction_repository.create() calls below reproduces
        # UC-07's documented failure point exactly: source debited, destination not yet
        # credited - see the forced-failure rollback test in
        # tests/integration/test_transfer_atomicity.py.
        transaction_repository.create(
            self._session,
            user_id=user.id,
            account_id=from_account.id,
            category_id=None,
            type=TransactionType.TRANSFER_OUT,
            amount=payload.amount,
            currency=payload.currency,
            description=description,
            merchant=None,
            notes=None,
            transaction_date=payload.transfer_date,
            transfer_id=transfer.id,
        )
        from_account.balance -= payload.amount

        transaction_repository.create(
            self._session,
            user_id=user.id,
            account_id=to_account.id,
            category_id=None,
            type=TransactionType.TRANSFER_IN,
            amount=payload.amount,
            currency=payload.currency,
            description=description,
            merchant=None,
            notes=None,
            transaction_date=payload.transfer_date,
            transfer_id=transfer.id,
        )
        to_account.balance += payload.amount

        await self._session.flush()
        AuditService.record(
            self._session,
            action="TRANSFER_CREATED",
            user_id=user.id,
            entity_type="transfer",
            entity_id=transfer.id,
            metadata={
                "amount": payload.amount,
                "currency": payload.currency,
                "transaction_date": payload.transfer_date,
                "account_id": from_account.id,
            },
        )
        await self._session.commit()
        await self._session.refresh(transfer)
        return transfer

    async def get_owned(self, *, user: User, transfer_id: int) -> Transfer:
        transfer = await transfer_repository.get_owned(
            self._session, transfer_id=transfer_id, user_id=user.id
        )
        if transfer is None:
            raise NotFoundError("The requested transfer was not found", code="TRANSFER_NOT_FOUND")
        return transfer

    async def list_for_user(
        self,
        *,
        user: User,
        account_id: int | None,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Transfer], int]:
        return await transfer_repository.list_for_user(
            self._session,
            user_id=user.id,
            account_id=account_id,
            date_from=date_from,
            date_to=date_to,
            page=page,
            page_size=page_size,
        )
