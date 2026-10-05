import uuid
from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel

from app.models.enums import CsvBatchStatus


class CsvRowIssue(BaseModel):
    row_number: int
    errors: list[str]


class CsvPotentialDuplicate(BaseModel):
    row_number: int
    description: str
    amount: Decimal
    transaction_date: str
    existing_transaction_id: int


class CsvImportPreviewResponse(BaseModel):
    batch_id: uuid.UUID
    total_rows: int
    valid_rows: int
    invalid_rows: list[CsvRowIssue]
    potential_duplicates: list[CsvPotentialDuplicate]


class CsvImportConfirmRequest(BaseModel):
    row_ids_to_import: list[int] | None = None


class CsvImportReport(BaseModel):
    batch_id: uuid.UUID
    status: CsvBatchStatus
    total_rows: int
    imported_rows: int
    skipped_rows: int
    status_url: str | None = None


class ResolvedCsvRow(TypedDict):
    """A validated row's fields, cached in raw_data["_resolved"] at preview time so
    confirm/processing never has to re-parse or re-resolve names - see module docstring.
    """

    account_id: str
    category_id: str
    type: str
    amount: str
    description: str
    transaction_date: str
    merchant: str | None
    notes: str | None
