"""CSV transaction import - UC-10. See docs/api-design.md §6 and docs/architecture/
data-flow.md §4.

Each CSV row must include: date (YYYY-MM-DD), description, amount (positive decimal),
type (INCOME/EXPENSE), category (resolved by name, system or the user's own), and account
(resolved by name, must belong to the user) - merchant/notes are optional. Resolution
happens once, at preview time; the resolved ids are cached in each VALID row's raw_data so
confirm/processing never has to re-resolve names (avoiding a TOCTOU gap if, say, a category
were renamed between preview and confirm).
"""

import csv
import datetime
import io
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    GoneError,
    NotFoundError,
    PayloadTooLargeError,
)
from app.models.account import Account
from app.models.category import Category
from app.models.csv_import import CsvImportBatch
from app.models.enums import CsvBatchStatus, CsvRowStatus
from app.models.user import User
from app.repositories import account_repository, category_repository, csv_import_repository
from app.schemas.csv_import import (
    CsvImportConfirmRequest,
    CsvImportPreviewResponse,
    CsvImportReport,
    CsvPotentialDuplicate,
    CsvRowIssue,
    ResolvedCsvRow,
)
from app.services.csv_import_processing_service import CsvImportProcessingService

_REQUIRED_COLUMNS = {"date", "description", "amount", "type", "category", "account"}


class CsvImportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def create_preview(
        self, *, user: User, filename: str, content: bytes
    ) -> CsvImportPreviewResponse:
        if not filename.lower().endswith(".csv"):
            raise BusinessRuleError("File must have a .csv extension", code="INVALID_FILE_FORMAT")
        if len(content) > self._settings.csv_import_max_file_size_bytes:
            raise PayloadTooLargeError(
                "The uploaded file exceeds the maximum allowed size", code="FILE_TOO_LARGE"
            )

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise BusinessRuleError(
                "File must be UTF-8 encoded text", code="INVALID_FILE_FORMAT"
            ) from exc

        reader = csv.DictReader(io.StringIO(text))
        fieldnames = set(reader.fieldnames or [])
        missing = _REQUIRED_COLUMNS - fieldnames
        if missing:
            raise BusinessRuleError(
                f"CSV is missing required columns: {', '.join(sorted(missing))}",
                code="INVALID_FILE_FORMAT",
            )

        raw_rows = list(reader)
        if not raw_rows:
            raise BusinessRuleError("CSV file has no data rows", code="INVALID_FILE_FORMAT")
        if len(raw_rows) > self._settings.csv_import_max_rows:
            raise BusinessRuleError(
                f"CSV exceeds the maximum of {self._settings.csv_import_max_rows} rows",
                code="FILE_TOO_LARGE",
            )

        batch = csv_import_repository.create_batch(
            self._session, user_id=user.id, filename=filename, total_rows=len(raw_rows)
        )
        await self._session.flush()  # assigns batch.id

        valid_count = 0
        invalid_issues: list[CsvRowIssue] = []
        duplicates: list[CsvPotentialDuplicate] = []

        for row_number, raw_row in enumerate(raw_rows, start=1):
            errors, resolved = await self._validate_row(user=user, raw_row=raw_row)
            if errors:
                csv_import_repository.create_row(
                    self._session,
                    batch_id=batch.id,
                    row_number=row_number,
                    raw_data=dict(raw_row),
                    status=CsvRowStatus.INVALID,
                    error_message="; ".join(errors),
                )
                invalid_issues.append(CsvRowIssue(row_number=row_number, errors=errors))
                continue

            assert resolved is not None  # noqa: S101 - mypy narrowing, not input validation
            existing = await csv_import_repository.find_duplicate_transaction(
                self._session,
                user_id=user.id,
                account_id=int(resolved["account_id"]),
                transaction_date=datetime.date.fromisoformat(resolved["transaction_date"]),
                amount=Decimal(resolved["amount"]),
                description=resolved["description"],
            )
            if existing is not None:
                raw_with_resolution = {**raw_row, "_resolved": resolved}
                csv_import_repository.create_row(
                    self._session,
                    batch_id=batch.id,
                    row_number=row_number,
                    raw_data=raw_with_resolution,
                    status=CsvRowStatus.DUPLICATE,
                    error_message=None,
                )
                duplicates.append(
                    CsvPotentialDuplicate(
                        row_number=row_number,
                        description=resolved["description"],
                        amount=Decimal(resolved["amount"]),
                        transaction_date=resolved["transaction_date"],
                        existing_transaction_id=existing.id,
                    )
                )
                continue

            raw_with_resolution = {**raw_row, "_resolved": resolved}
            csv_import_repository.create_row(
                self._session,
                batch_id=batch.id,
                row_number=row_number,
                raw_data=raw_with_resolution,
                status=CsvRowStatus.VALID,
                error_message=None,
            )
            valid_count += 1

        await self._session.commit()
        return CsvImportPreviewResponse(
            batch_id=batch.id,
            total_rows=len(raw_rows),
            valid_rows=valid_count,
            invalid_rows=invalid_issues,
            potential_duplicates=duplicates,
        )

    @staticmethod
    def _parse_date(raw_row: dict[str, str], errors: list[str]) -> datetime.date | None:
        date_str = (raw_row.get("date") or "").strip()
        try:
            return datetime.date.fromisoformat(date_str)
        except ValueError:
            errors.append("date must be in YYYY-MM-DD format")
            return None

    @staticmethod
    def _parse_amount(raw_row: dict[str, str], errors: list[str]) -> Decimal | None:
        amount_str = (raw_row.get("amount") or "").strip()
        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            errors.append("amount must be a valid decimal number")
            return None
        if amount <= 0:
            errors.append("amount must be a positive number")
            return None
        return amount

    @staticmethod
    def _parse_type(raw_row: dict[str, str], errors: list[str]) -> str:
        type_str = (raw_row.get("type") or "").strip().upper()
        if type_str not in ("INCOME", "EXPENSE"):
            errors.append("type must be INCOME or EXPENSE")
        return type_str

    @staticmethod
    def _parse_description(raw_row: dict[str, str], errors: list[str]) -> str:
        description = (raw_row.get("description") or "").strip()
        if not description:
            errors.append("description is required")
        return description

    async def _resolve_account(
        self, raw_row: dict[str, str], user: User, errors: list[str]
    ) -> Account | None:
        account_name = (raw_row.get("account") or "").strip()
        if not account_name:
            errors.append("account is required")
            return None
        account = await account_repository.get_by_name_for_user(
            self._session, name=account_name, user_id=user.id
        )
        if account is None:
            errors.append(f"Unknown account: {account_name}")
        elif account.is_archived:
            errors.append(f"Account is archived: {account_name}")
        return account

    async def _resolve_category(
        self, raw_row: dict[str, str], user: User, type_str: str, errors: list[str]
    ) -> Category | None:
        category_name = (raw_row.get("category") or "").strip()
        if not category_name:
            errors.append("category is required")
            return None
        category = await category_repository.get_by_name_visible_to_user(
            self._session, name=category_name, user_id=user.id
        )
        if category is None:
            errors.append(f"Unknown category: {category_name}")
        elif type_str in ("INCOME", "EXPENSE") and category.type.value != type_str:
            errors.append(f"Category '{category_name}' does not match type {type_str}")
        return category

    async def _validate_row(
        self, *, user: User, raw_row: dict[str, str]
    ) -> tuple[list[str], ResolvedCsvRow | None]:
        errors: list[str] = []
        parsed_date = self._parse_date(raw_row, errors)
        amount = self._parse_amount(raw_row, errors)
        type_str = self._parse_type(raw_row, errors)
        description = self._parse_description(raw_row, errors)
        account = await self._resolve_account(raw_row, user, errors)
        category = await self._resolve_category(raw_row, user, type_str, errors)

        if errors:
            return errors, None

        # mypy narrowing, not input validation - guaranteed non-None when errors is empty.
        assert parsed_date is not None  # noqa: S101
        assert amount is not None  # noqa: S101
        assert account is not None  # noqa: S101
        assert category is not None  # noqa: S101
        resolved: ResolvedCsvRow = {
            "account_id": str(account.id),
            "category_id": str(category.id),
            "type": type_str,
            "amount": str(amount),
            "description": description,
            "transaction_date": parsed_date.isoformat(),
            "merchant": (raw_row.get("merchant") or "").strip() or None,
            "notes": (raw_row.get("notes") or "").strip() or None,
        }
        return [], resolved

    async def _get_owned_batch(self, *, user: User, batch_id: uuid.UUID) -> CsvImportBatch:
        batch = await csv_import_repository.get_owned_batch(
            self._session, batch_id=batch_id, user_id=user.id
        )
        if batch is None:
            raise NotFoundError("The requested import batch was not found", code="BATCH_NOT_FOUND")
        return batch

    async def get_batch(self, *, user: User, batch_id: uuid.UUID) -> CsvImportReport:
        batch = await self._get_owned_batch(user=user, batch_id=batch_id)
        return CsvImportReport(
            batch_id=batch.id,
            status=batch.status,
            total_rows=batch.total_rows,
            imported_rows=batch.imported_rows,
            skipped_rows=batch.skipped_rows,
        )

    async def confirm(
        self, *, user: User, batch_id: uuid.UUID, payload: CsvImportConfirmRequest
    ) -> CsvImportReport:
        batch = await self._get_owned_batch(user=user, batch_id=batch_id)
        if batch.status != CsvBatchStatus.PENDING_PREVIEW:
            raise ConflictError(
                "This import batch has already been confirmed", code="BATCH_ALREADY_CONFIRMED"
            )

        ttl = datetime.timedelta(hours=self._settings.csv_import_preview_ttl_hours)
        if datetime.datetime.now(datetime.UTC) > batch.created_at + ttl:
            raise GoneError(
                "This import preview has expired; please re-upload the file",
                code="BATCH_EXPIRED",
            )

        row_count = (
            len(payload.row_ids_to_import)
            if payload.row_ids_to_import is not None
            else batch.total_rows
        )

        if row_count > self._settings.csv_import_sync_row_threshold:
            batch.status = CsvBatchStatus.PROCESSING
            await self._session.commit()
            from app.workers.tasks import (
                process_import_batch_task,  # avoid import cycle at module load
            )

            process_import_batch_task.delay(str(batch.id), payload.row_ids_to_import)
            return CsvImportReport(
                batch_id=batch.id,
                status=batch.status,
                total_rows=batch.total_rows,
                imported_rows=0,
                skipped_rows=0,
                status_url=f"/api/v1/transactions/import/{batch.id}",
            )

        processing_service = CsvImportProcessingService(self._session)
        imported, skipped = await processing_service.process(
            batch=batch, row_ids_to_import=payload.row_ids_to_import
        )
        batch.status = CsvBatchStatus.COMPLETED
        batch.imported_rows = imported
        batch.skipped_rows = skipped
        await self._session.commit()
        return CsvImportReport(
            batch_id=batch.id,
            status=batch.status,
            total_rows=batch.total_rows,
            imported_rows=imported,
            skipped_rows=skipped,
        )
