import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Append-only. No update/delete endpoint ever targets this table - see FR-AUDIT-03."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nullable: system/worker-initiated actions (e.g. recurring transaction processing)
    # have no human actor.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Python attribute name avoids colliding with Base.metadata; DB column stays "metadata".
    # Populated from an explicit per-action allow-list (FR-AUDIT-02) - never a raw request
    # body dump - so secrets can never leak into an audit record.
    audit_metadata: Mapped[dict[str, object] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_entity_type_entity_id", "entity_type", "entity_id"),
    )
