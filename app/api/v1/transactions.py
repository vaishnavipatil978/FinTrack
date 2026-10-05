import datetime
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Header, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_app_settings,
    get_current_user,
    get_idempotency_context,
    get_report_cache,
)
from app.core.cache import ReportCache
from app.core.config import Settings
from app.core.idempotency import Producer, run_idempotent
from app.db.session import get_db_session
from app.models.enums import TransactionType
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.csv_import import (
    CsvImportConfirmRequest,
    CsvImportPreviewResponse,
    CsvImportReport,
)
from app.schemas.pagination import total_pages
from app.schemas.transaction import (
    TransactionCreate,
    TransactionListResponse,
    TransactionRead,
    TransactionUpdate,
)
from app.services.csv_import_service import CsvImportService
from app.services.transaction_service import TransactionService

IdempotencyContext = tuple[Redis | None, bool, int]

router = APIRouter(prefix="/transactions", tags=["Transactions"])


def get_transaction_service(
    session: AsyncSession = Depends(get_db_session),
) -> TransactionService:
    return TransactionService(session)


def get_csv_import_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_app_settings),
) -> CsvImportService:
    return CsvImportService(session, settings)


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    payload: TransactionCreate,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
    report_cache: ReportCache = Depends(get_report_cache),
    idem: IdempotencyContext = Depends(get_idempotency_context),
) -> JSONResponse:
    async def produce() -> tuple[int, dict[str, object]]:
        transaction = await transaction_service.create(user=current_user, payload=payload)
        await report_cache.invalidate_user(current_user.id)
        body = TransactionRead.model_validate(transaction).model_dump(mode="json")
        return status.HTTP_201_CREATED, body

    code, body = await _maybe_idempotent(idem, current_user.id, idempotency_key, produce)
    return JSONResponse(status_code=code, content=body)


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    account_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    type: TransactionType | None = Query(default=None),
    date_from: datetime.date | None = Query(default=None),
    date_to: datetime.date | None = Query(default=None),
    amount_min: Decimal | None = Query(default=None),
    amount_max: Decimal | None = Query(default=None),
    search: str | None = Query(default=None),
    sort_by: str = Query(default="transaction_date", pattern="^(transaction_date|amount)$"),
    sort_dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> TransactionListResponse:
    items, total = await transaction_service.list_for_user(
        user=current_user,
        account_id=account_id,
        category_id=category_id,
        type=type,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        search=search,
        sort_by=sort_by,  # type: ignore[arg-type]  # validated by the Query pattern above
        sort_dir=sort_dir,  # type: ignore[arg-type]
        page=page,
        page_size=page_size,
    )
    return TransactionListResponse(
        items=[TransactionRead.model_validate(item) for item in items],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=total_pages(total, page_size),
    )


# Registered before "/{transaction_id}" - same reasoning as budgets' "/summary" route:
# Starlette matches path templates in registration order, and {transaction_id} would
# otherwise swallow "import" as its (int-conversion-failing) value.
@router.post("/import", response_model=CsvImportPreviewResponse)
async def import_transactions_preview(
    current_user: User = Depends(get_current_user),
    csv_import_service: CsvImportService = Depends(get_csv_import_service),
    file: UploadFile = File(...),
) -> CsvImportPreviewResponse:
    content = await file.read()
    return await csv_import_service.create_preview(
        user=current_user, filename=file.filename or "upload.csv", content=content
    )


@router.post("/import/{batch_id}/confirm", response_model=CsvImportReport)
async def confirm_import(
    batch_id: uuid.UUID,
    payload: CsvImportConfirmRequest,
    current_user: User = Depends(get_current_user),
    csv_import_service: CsvImportService = Depends(get_csv_import_service),
    report_cache: ReportCache = Depends(get_report_cache),
) -> CsvImportReport:
    report = await csv_import_service.confirm(user=current_user, batch_id=batch_id, payload=payload)
    await report_cache.invalidate_user(current_user.id)
    return report


@router.get("/import/{batch_id}", response_model=CsvImportReport)
async def get_import_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    csv_import_service: CsvImportService = Depends(get_csv_import_service),
) -> CsvImportReport:
    return await csv_import_service.get_batch(user=current_user, batch_id=batch_id)


@router.get("/{transaction_id}", response_model=TransactionRead)
async def get_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
) -> Transaction:
    return await transaction_service.get_owned(user=current_user, transaction_id=transaction_id)


@router.patch("/{transaction_id}", response_model=TransactionRead)
async def update_transaction(
    transaction_id: int,
    payload: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
    report_cache: ReportCache = Depends(get_report_cache),
) -> Transaction:
    transaction = await transaction_service.update(
        user=current_user, transaction_id=transaction_id, payload=payload
    )
    await report_cache.invalidate_user(current_user.id)
    return transaction


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: int,
    current_user: User = Depends(get_current_user),
    transaction_service: TransactionService = Depends(get_transaction_service),
    report_cache: ReportCache = Depends(get_report_cache),
) -> None:
    await transaction_service.void(user=current_user, transaction_id=transaction_id)
    await report_cache.invalidate_user(current_user.id)


async def _maybe_idempotent(
    idem: IdempotencyContext,
    user_id: int,
    idempotency_key: str | None,
    produce: Producer,
) -> tuple[int, dict[str, object]]:
    if idempotency_key is None:
        return await produce()
    redis, enabled, ttl = idem
    return await run_idempotent(
        redis,
        enabled=enabled,
        ttl_seconds=ttl,
        user_id=user_id,
        idempotency_key=idempotency_key,
        producer=produce,
    )
