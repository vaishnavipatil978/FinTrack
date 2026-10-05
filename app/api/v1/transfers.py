import datetime

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_idempotency_context, get_report_cache
from app.api.v1.transactions import IdempotencyContext, _maybe_idempotent
from app.core.cache import ReportCache
from app.db.session import get_db_session
from app.models.transfer import Transfer
from app.models.user import User
from app.schemas.pagination import total_pages
from app.schemas.transfer import TransferCreate, TransferListResponse, TransferRead
from app.services.transfer_service import TransferService

router = APIRouter(prefix="/transfers", tags=["Transfers"])


def get_transfer_service(session: AsyncSession = Depends(get_db_session)) -> TransferService:
    return TransferService(session)


@router.post("", response_model=TransferRead, status_code=status.HTTP_201_CREATED)
async def create_transfer(
    payload: TransferCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    transfer_service: TransferService = Depends(get_transfer_service),
    report_cache: ReportCache = Depends(get_report_cache),
    idem: IdempotencyContext = Depends(get_idempotency_context),
) -> JSONResponse:
    async def produce() -> tuple[int, dict[str, object]]:
        transfer = await transfer_service.create(user=current_user, payload=payload)
        await report_cache.invalidate_user(current_user.id)
        return status.HTTP_201_CREATED, TransferRead.model_validate(transfer).model_dump(
            mode="json"
        )

    code, body = await _maybe_idempotent(idem, current_user.id, idempotency_key, produce)
    return JSONResponse(status_code=code, content=body)


@router.get("", response_model=TransferListResponse)
async def list_transfers(
    account_id: int | None = Query(default=None),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    transfer_service: TransferService = Depends(get_transfer_service),
) -> TransferListResponse:
    items, total = await transfer_service.list_for_user(
        user=current_user,
        account_id=account_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    return TransferListResponse(
        items=[TransferRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


@router.get("/{transfer_id}", response_model=TransferRead)
async def get_transfer(
    transfer_id: int,
    current_user: User = Depends(get_current_user),
    transfer_service: TransferService = Depends(get_transfer_service),
) -> Transfer:
    return await transfer_service.get_owned(user=current_user, transfer_id=transfer_id)
