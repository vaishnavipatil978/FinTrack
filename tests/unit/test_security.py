import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    verify_password,
)

SECRET = "unit-test-secret-key-0123456789abcdef0123456789"


def test_hashed_password_is_not_plaintext() -> None:
    hashed = hash_password("correct horse battery staple")

    assert hashed != "correct horse battery staple"
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_correct_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")

    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_malformed_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-real-hash") is False


def test_opaque_tokens_are_unique_and_high_entropy() -> None:
    first = generate_opaque_token()
    second = generate_opaque_token()

    assert first != second
    assert len(first) >= 48


def test_hash_opaque_token_is_deterministic_and_one_way() -> None:
    token = generate_opaque_token()

    assert hash_opaque_token(token) == hash_opaque_token(token)
    assert hash_opaque_token(token) != token


def test_access_token_round_trips() -> None:
    token = create_access_token(
        user_id=42, role="USER", secret_key=SECRET, algorithm="HS256", expires_minutes=15
    )

    payload = decode_access_token(token, secret_key=SECRET, algorithm="HS256")

    assert payload["sub"] == "42"
    assert payload["role"] == "USER"
    assert payload["type"] == "access"
    assert "jti" in payload


def test_expired_access_token_is_rejected() -> None:
    token = create_access_token(
        user_id=1, role="USER", secret_key=SECRET, algorithm="HS256", expires_minutes=-1
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(token, secret_key=SECRET, algorithm="HS256")


def test_access_token_with_wrong_secret_is_rejected() -> None:
    token = create_access_token(
        user_id=1, role="USER", secret_key=SECRET, algorithm="HS256", expires_minutes=15
    )

    with pytest.raises(InvalidTokenError):
        decode_access_token(
            token, secret_key="a-completely-different-secret-key", algorithm="HS256"
        )


def test_two_tokens_for_the_same_user_have_different_jti() -> None:
    first = decode_access_token(
        create_access_token(
            user_id=1, role="USER", secret_key=SECRET, algorithm="HS256", expires_minutes=15
        ),
        secret_key=SECRET,
        algorithm="HS256",
    )
    second = decode_access_token(
        create_access_token(
            user_id=1, role="USER", secret_key=SECRET, algorithm="HS256", expires_minutes=15
        ),
        secret_key=SECRET,
        algorithm="HS256",
    )

    assert first["jti"] != second["jti"]
