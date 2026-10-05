import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models._enum_column import pg_enum
from app.models.base import Base, TimestampMixin
from app.models.enums import CsvBatchStatus, CsvRowStatus

if TYPE_CHECKING:
    from app.models.transaction import Transaction


class CsvImportBatch(TimestampMixin, Base):
    __tablename__ = "csv_import_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[CsvBatchStatus] = mapped_column(
        pg_enum(CsvBatchStatus, "csv_batch_status"), nullable=False
    )
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_report: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    rows: Mapped[list["CsvImportRow"]] = relationship(back_populates="batch")


class CsvImportRow(Base):
    __tablename__ = "csv_import_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("csv_import_batches.id"), nullable=False, index=True
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[CsvRowStatus] = mapped_column(
        pg_enum(CsvRowStatus, "csv_row_status"), nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )

    batch: Mapped["CsvImportBatch"] = relationship(back_populates="rows")
    resolved_transaction: Mapped["Transaction | None"] = relationship()
