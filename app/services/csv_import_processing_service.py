"""Materializes the rows a CSV import batch's preview already validated and resolved.
Shared by the synchronous confirm() path and the async Celery task (process_import_batch_task)
so there is exactly one code path for "turn a confirmed row into a real transaction" -
see docs/architecture/data-flow.md §4.
"""

import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.csv_import import CsvImportBatch
from app.models.enums import CsvRowStatus, TransactionType
from app.repositories import account_repository, csv_import_repository, transaction_repository
from app.schemas.csv_import import ResolvedCsvRow
from app.services.audit_service import AuditService
from app.services.transaction_service import signed_effect


class CsvImportProcessingService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def process(
        self, *, batch: CsvImportBatch, row_ids_to_import: list[int] | None
    ) -> tuple[int, int]:
        """Returns (imported_count, skipped_count). Rows already VALID but not selected for
        import are marked SKIPPED; INVALID/DUPLICATE rows are left as the preview found them.
        """
        rows = await csv_import_repository.list_rows_for_batch(self._session, batch_id=batch.id)
        selected_ids = set(row_ids_to_import) if row_ids_to_import is not None else None

        imported = 0
        for row in rows:
            if row.status != CsvRowStatus.VALID:
                continue
            should_import = selected_ids is None or row.id in selected_ids
            if not should_import:
                row.status = CsvRowStatus.SKIPPED
                continue

            resolved = cast(ResolvedCsvRow, row.raw_data["_resolved"])
            account = await account_repository.get_owned_for_update(
                self._session, account_id=int(resolved["account_id"]), user_id=batch.user_id
            )
            if account is None:
                # Re-validated at preview time; only reachable if the account was deleted
                # between preview and confirm, which the app never allows (archive-only).
                row.status = CsvRowStatus.INVALID
                row.error_message = "Account no longer exists"
                continue
            transaction_type = TransactionType(resolved["type"])
            amount = Decimal(resolved["amount"])

            category_id_raw = resolved["category_id"]
            transaction = transaction_repository.create(
                self._session,
                user_id=batch.user_id,
                account_id=account.id,
                category_id=int(category_id_raw),
                type=transaction_type,
                amount=amount,
                currency=account.currency,
                description=resolved["description"],
                merchant=resolved["merchant"],
                notes=resolved["notes"],
                transaction_date=datetime.date.fromisoformat(resolved["transaction_date"]),
            )
            account.balance += signed_effect(transaction_type, amount)
            await self._session.flush()

            row.status = CsvRowStatus.IMPORTED
            row.resolved_transaction_id = transaction.id
            imported += 1

        skipped = batch.total_rows - imported
        AuditService.record(
            self._session,
            action="CSV_IMPORTED",
            user_id=batch.user_id,
            entity_type="csv_batch",
            entity_id=str(batch.id),
            metadata={"imported_rows": imported, "skipped_rows": skipped},
        )
        return imported, skipped
