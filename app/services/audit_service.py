"""Append-only audit trail - FR-AUDIT-01..03, docs/architecture/security-architecture.md §7.

Records are added to the caller's session so an audit row commits or rolls back together
with the business write it describes. Metadata is filtered through an allowlist, so
passwords, tokens, and raw request bodies can never reach the audit table even if a caller
passes them by mistake.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import get_request_id
from app.models.audit_log import AuditLog

_ALLOWED_METADATA_KEYS = frozenset(
    {
        "amount",
        "currency",
        "transaction_date",
        "scheduled_date",
        "account_id",
        "category_id",
        "transaction_id",
        "transfer_id",
        "budget_id",
        "goal_id",
        "rule_id",
        "batch_id",
        "imported_rows",
        "skipped_rows",
        "type",
        "period_month",
        "period_year",
        "name",
    }
)


class AuditService:
    @staticmethod
    def record(
        session: AsyncSession,
        *,
        action: str,
        user_id: int | None,
        entity_type: str | None = None,
        entity_id: int | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_metadata = {
            key: str(value)
            for key, value in (metadata or {}).items()
            if key in _ALLOWED_METADATA_KEYS and value is not None
        }
        session.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                audit_metadata=safe_metadata or None,
                request_id=get_request_id(),
            )
        )
