import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_report_cache
from app.core.cache import ReportCache
from app.db.session import get_db_session
from app.models.account import Account
from app.models.user import User
from app.schemas.account import AccountBalanceRead, AccountCreate, AccountRead, AccountUpdate
from app.services.account_service import AccountService

router = APIRouter(prefix="/accounts", tags=["Accounts"])


def get_account_service(session: AsyncSession = Depends(get_db_session)) -> AccountService:
    return AccountService(session)


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    report_cache: ReportCache = Depends(get_report_cache),
) -> Account:
    account = await account_service.create(user=current_user, payload=payload)
    await report_cache.invalidate_user(current_user.id)
    return account


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    include_archived: bool = Query(default=False),
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> list[Account]:
    return await account_service.list_for_user(user=current_user, include_archived=include_archived)


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> Account:
    return await account_service.get_owned(user=current_user, account_id=account_id)


@router.patch("/{account_id}", response_model=AccountRead)
async def update_account(
    account_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> Account:
    return await account_service.update(user=current_user, account_id=account_id, payload=payload)


@router.post("/{account_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> None:
    await account_service.archive(user=current_user, account_id=account_id)


@router.get("/{account_id}/balance", response_model=AccountBalanceRead)
async def get_account_balance(
    account_id: int,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountBalanceRead:
    account = await account_service.get_owned(user=current_user, account_id=account_id)
    return AccountBalanceRead(
        account_id=account.id,
        balance=account.balance,
        currency=account.currency,
        as_of=datetime.datetime.now(datetime.UTC),
    )
