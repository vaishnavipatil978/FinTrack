from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.audit_service import AuditService


class _CapturingSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def test_audit_metadata_drops_keys_not_on_the_allowlist() -> None:
    session = _CapturingSession()

    AuditService.record(
        cast(AsyncSession, session),
        action="LOGIN",
        user_id=1,
        metadata={
            "amount": "10.00",
            "password": "hunter2",
            "access_token": "abc",
            "body": {"x": 1},
        },
    )

    assert session.added[0].audit_metadata == {"amount": "10.00"}


def test_audit_metadata_is_none_when_nothing_survives_the_filter() -> None:
    session = _CapturingSession()

    AuditService.record(
        cast(AsyncSession, session),
        action="LOGOUT",
        user_id=1,
        metadata={"refresh_token": "x"},
    )

    assert session.added[0].audit_metadata is None
