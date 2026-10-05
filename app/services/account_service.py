from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.account import Account
from app.models.enums import AccountType
from app.models.user import User
from app.repositories import account_repository
from app.schemas.account import AccountCreate, AccountUpdate
from app.services.audit_service import AuditService


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user: User, payload: AccountCreate) -> Account:
        account = account_repository.create(
            self._session,
            user_id=user.id,
            name=payload.name,
            type=payload.type,
            currency=payload.currency,
            balance=payload.opening_balance,
            # CREDIT_CARD accounts are expected to run a balance - see
            # docs/database-design.md §3.3. Not client-controlled: keeps the create
            # contract simple and prevents a user from disabling this on the wrong
            # account type by mistake.
            allow_negative_balance=payload.type == AccountType.CREDIT_CARD,
        )
        await self._session.flush()
        AuditService.record(
            self._session,
            action="ACCOUNT_CREATED",
            user_id=user.id,
            entity_type="account",
            entity_id=account.id,
            metadata={"currency": account.currency, "account_id": account.id},
        )
        await self._session.commit()
        await self._session.refresh(account)
        return account

    async def list_for_user(self, *, user: User, include_archived: bool) -> list[Account]:
        return await account_repository.list_for_user(
            self._session, user_id=user.id, include_archived=include_archived
        )

    async def get_owned(self, *, user: User, account_id: int) -> Account:
        account = await account_repository.get_owned(
            self._session, account_id=account_id, user_id=user.id
        )
        if account is None:
            # 404, not 403: does not confirm to the caller that this id belongs to
            # someone else - security-architecture.md §2.
            raise NotFoundError("The requested account was not found", code="ACCOUNT_NOT_FOUND")
        return account

    async def update(self, *, user: User, account_id: int, payload: AccountUpdate) -> Account:
        account = await self.get_owned(user=user, account_id=account_id)
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(account, field, value)
        await self._session.commit()
        await self._session.refresh(account)
        return account

    async def archive(self, *, user: User, account_id: int) -> None:
        account = await self.get_owned(user=user, account_id=account_id)
        if account.is_archived:
            return  # idempotent - see docs/api-design.md §4
        account.is_archived = True
        await self._session.commit()
