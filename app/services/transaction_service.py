import datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.models.account import Account
from app.models.category import Category
from app.models.enums import TransactionType
from app.models.transaction import Transaction
from app.models.user import User
from app.repositories import (
    account_repository,
    budget_repository,
    category_repository,
    transaction_repository,
)
from app.repositories.transaction_repository import SortBy, SortDir
from app.schemas.transaction import TransactionCreate, TransactionUpdate
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.period import month_date_range

# INCOME credits an account, EXPENSE debits it - the only two directions a client can
# request directly (see TransactionDirection); TRANSFER_IN/OUT are TransferService-only.
_SIGN: dict[TransactionType, int] = {
    TransactionType.INCOME: 1,
    TransactionType.EXPENSE: -1,
    TransactionType.TRANSFER_IN: 1,
    TransactionType.TRANSFER_OUT: -1,
}


def signed_effect(type: TransactionType, amount: Decimal) -> Decimal:
    return _SIGN[type] * amount


class TransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _get_locked_account(self, *, user: User, account_id: int) -> Account:
        account = await account_repository.get_owned_for_update(
            self._session, account_id=account_id, user_id=user.id
        )
        if account is None:
            raise NotFoundError("The requested account was not found", code="ACCOUNT_NOT_FOUND")
        return account

    async def _get_valid_category(
        self, *, user: User, category_id: int, expected_type: TransactionType
    ) -> Category:
        category = await category_repository.get_visible_to_user(
            self._session, category_id=category_id, user_id=user.id
        )
        if category is None:
            raise NotFoundError("The requested category was not found", code="CATEGORY_NOT_FOUND")
        if category.is_archived:
            raise BusinessRuleError(
                "This category is archived and cannot be used for new transactions",
                code="CATEGORY_ARCHIVED",
            )
        if category.type.value != expected_type.value:
            raise BusinessRuleError(
                "This category cannot be used with this transaction type",
                code="CATEGORY_TYPE_MISMATCH",
            )
        return category

    async def create(self, *, user: User, payload: TransactionCreate) -> Transaction:
        transaction_type = TransactionType(payload.type.value)
        account = await self._get_locked_account(user=user, account_id=payload.account_id)
        if account.is_archived:
            raise BusinessRuleError(
                "This account is archived and cannot receive new transactions",
                code="ACCOUNT_ARCHIVED",
            )
        await self._get_valid_category(
            user=user, category_id=payload.category_id, expected_type=transaction_type
        )

        transaction = transaction_repository.create(
            self._session,
            user_id=user.id,
            account_id=account.id,
            category_id=payload.category_id,
            type=transaction_type,
            amount=payload.amount,
            currency=payload.currency,
            description=payload.description,
            merchant=payload.merchant,
            notes=payload.notes,
            transaction_date=payload.transaction_date,
        )
        account.balance += signed_effect(transaction_type, payload.amount)
        await self._session.flush()
        AuditService.record(
            self._session,
            action="TRANSACTION_CREATED",
            user_id=user.id,
            entity_type="transaction",
            entity_id=transaction.id,
            metadata={
                "amount": payload.amount,
                "currency": payload.currency,
                "account_id": account.id,
                "category_id": payload.category_id,
                "type": transaction_type.value,
                "transaction_date": payload.transaction_date,
            },
        )
        if transaction_type == TransactionType.EXPENSE:
            await self._notify_if_budget_crossed(
                user=user,
                category_id=payload.category_id,
                transaction_date=payload.transaction_date,
                amount=payload.amount,
            )
        await self._session.commit()
        await self._session.refresh(transaction)
        return transaction

    async def _notify_if_budget_crossed(
        self, *, user: User, category_id: int, transaction_date: datetime.date, amount: Decimal
    ) -> None:
        """FR-NOTIF-01: notify once, on the transaction that pushes spend past the budget."""
        month_start = transaction_date.replace(day=1)
        budget = await budget_repository.get_for_period(
            self._session,
            user_id=user.id,
            category_id=category_id,
            period_month=month_start.month,
            period_year=month_start.year,
        )
        if budget is None:
            return
        date_from, date_to = month_date_range(month_start.year, month_start.month)
        spent_now = await transaction_repository.sum_expense_for_category_period(
            self._session,
            user_id=user.id,
            category_id=category_id,
            date_from=date_from,
            date_to=date_to,
        )
        if spent_now - amount <= budget.target_amount < spent_now:
            await NotificationService(self._session).notify(
                user_id=user.id,
                type="BUDGET_EXCEEDED",
                title="Budget exceeded",
                message=f"You have exceeded your budget for {month_start:%B %Y}.",
                metadata={"budget_id": budget.id},
            )

    async def get_owned(self, *, user: User, transaction_id: int) -> Transaction:
        transaction = await transaction_repository.get_owned(
            self._session, transaction_id=transaction_id, user_id=user.id
        )
        if transaction is None:
            raise NotFoundError(
                "The requested transaction was not found", code="TRANSACTION_NOT_FOUND"
            )
        return transaction

    async def list_for_user(
        self,
        *,
        user: User,
        account_id: int | None,
        category_id: int | None,
        type: TransactionType | None,
        date_from: datetime.date | None,
        date_to: datetime.date | None,
        amount_min: Decimal | None,
        amount_max: Decimal | None,
        search: str | None,
        sort_by: SortBy,
        sort_dir: SortDir,
        page: int,
        page_size: int,
    ) -> tuple[list[Transaction], int]:
        return await transaction_repository.list_for_user(
            self._session,
            user_id=user.id,
            account_id=account_id,
            category_id=category_id,
            type=type,
            date_from=date_from,
            date_to=date_to,
            amount_min=amount_min,
            amount_max=amount_max,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            page=page,
            page_size=page_size,
        )

    async def update(
        self, *, user: User, transaction_id: int, payload: TransactionUpdate
    ) -> Transaction:
        transaction = await self.get_owned(user=user, transaction_id=transaction_id)
        if transaction.is_voided:
            raise BusinessRuleError(
                "A voided transaction cannot be edited", code="TRANSACTION_VOIDED"
            )
        account = await self._get_locked_account(user=user, account_id=transaction.account_id)

        new_amount = payload.amount if payload.amount is not None else transaction.amount
        if payload.category_id is not None and payload.category_id != transaction.category_id:
            await self._get_valid_category(
                user=user, category_id=payload.category_id, expected_type=transaction.type
            )
            transaction.category_id = payload.category_id

        if payload.amount is not None:
            # Reverse the old effect, apply the new one - both within this one DB
            # transaction, so the balance is never observed half-updated.
            account.balance -= signed_effect(transaction.type, transaction.amount)
            account.balance += signed_effect(transaction.type, new_amount)
            transaction.amount = new_amount
        if payload.transaction_date is not None:
            transaction.transaction_date = payload.transaction_date
        if payload.description is not None:
            transaction.description = payload.description
        if payload.merchant is not None:
            transaction.merchant = payload.merchant
        if payload.notes is not None:
            transaction.notes = payload.notes

        AuditService.record(
            self._session,
            action="TRANSACTION_UPDATED",
            user_id=user.id,
            entity_type="transaction",
            entity_id=transaction.id,
            metadata={
                "amount": transaction.amount,
                "transaction_date": transaction.transaction_date,
            },
        )
        await self._session.commit()
        await self._session.refresh(transaction)
        return transaction

    async def void(self, *, user: User, transaction_id: int) -> None:
        transaction = await self.get_owned(user=user, transaction_id=transaction_id)
        if transaction.is_voided:
            return  # idempotent
        account = await self._get_locked_account(user=user, account_id=transaction.account_id)
        account.balance -= signed_effect(transaction.type, transaction.amount)
        transaction.is_voided = True
        AuditService.record(
            self._session,
            action="TRANSACTION_DELETED",
            user_id=user.id,
            entity_type="transaction",
            entity_id=transaction.id,
        )
        await self._session.commit()
