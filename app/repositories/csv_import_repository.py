import datetime
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.csv_import import CsvImportBatch, CsvImportRow
from app.models.enums import CsvBatchStatus, CsvRowStatus
from app.models.transaction import Transaction


def create_batch(
    session: AsyncSession, *, user_id: int, filename: str, total_rows: int
) -> CsvImportBatch:
    batch = CsvImportBatch(
        user_id=user_id,
        filename=filename,
        status=CsvBatchStatus.PENDING_PREVIEW,
        total_rows=total_rows,
    )
    session.add(batch)
    return batch


def create_row(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    row_number: int,
    raw_data: dict[str, object],
    status: CsvRowStatus,
    error_message: str | None,
) -> CsvImportRow:
    row = CsvImportRow(
        batch_id=batch_id,
        row_number=row_number,
        raw_data=raw_data,
        status=status,
        error_message=error_message,
    )
    session.add(row)
    return row


async def get_by_id(session: AsyncSession, *, batch_id: uuid.UUID) -> CsvImportBatch | None:
    """Unscoped lookup for worker use - the background task has no "current user" to scope
    by, and batch_id is an unguessable UUID only ever handed out by confirm() to its owner.
    API code must use get_owned_batch below, never this.
    """
    return await session.get(CsvImportBatch, batch_id)


async def get_owned_batch(
    session: AsyncSession, *, batch_id: uuid.UUID, user_id: int
) -> CsvImportBatch | None:
    result = await session.execute(
        select(CsvImportBatch).where(
            CsvImportBatch.id == batch_id, CsvImportBatch.user_id == user_id
        )
    )
    return result.scalar_one_or_none()


async def list_rows_for_batch(session: AsyncSession, *, batch_id: uuid.UUID) -> list[CsvImportRow]:
    result = await session.execute(
        select(CsvImportRow)
        .where(CsvImportRow.batch_id == batch_id)
        .order_by(CsvImportRow.row_number)
    )
    return list(result.scalars().all())


async def find_duplicate_transaction(
    session: AsyncSession,
    *,
    user_id: int,
    account_id: int,
    transaction_date: datetime.date,
    amount: Decimal,
    description: str,
) -> Transaction | None:
    """FR-CSV-05: a row matching an existing transaction on account+date+amount+description
    is flagged for user confirmation rather than silently imported.
    """
    result = await session.execute(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.account_id == account_id,
            Transaction.transaction_date == transaction_date,
            Transaction.amount == amount,
            Transaction.description == description,
            Transaction.is_voided.is_(False),
        )
    )
    return result.scalars().first()
