import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_password_hasher = PasswordHasher()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time verification via argon2's own comparison - never a manual == check."""
    try:
        return _password_hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_opaque_token() -> str:
    """A high-entropy random string for refresh/reset tokens - not a JWT, not self-describing.
    See docs/architecture/security-architecture.md §1.3.
    """
    return secrets.token_urlsafe(48)


def hash_opaque_token(token: str) -> str:
    """SHA-256 for at-rest storage of refresh/reset tokens - only the hash is persisted,
    the raw value is returned to the client exactly once, at issuance.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(
    *, user_id: int, role: str, secret_key: str, algorithm: str, expires_minutes: int
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "type": TokenType.ACCESS.value,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret_key, algorithm=algorithm)


class InvalidTokenError(Exception):
    """Raised for any decode failure (bad signature, expired, wrong type) - callers don't
    need to distinguish the reason; all of them mean "reject this token".
    """


def decode_access_token(token: str, *, secret_key: str, algorithm: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(str(exc)) from exc
    if payload.get("type") != TokenType.ACCESS.value:
        raise InvalidTokenError("Not an access token")
    return payload
