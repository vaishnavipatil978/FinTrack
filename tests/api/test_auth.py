from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token
from app.services.auth_service import AuthService


async def _register(
    client: AsyncClient, *, email: str = "ada@example.com", **overrides: Any
) -> dict[str, Any]:
    payload = {
        "email": email,
        "password": "correct-horse-battery-staple",
        "full_name": "Ada Lovelace",
        **overrides,
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _login(
    client: AsyncClient,
    *,
    email: str = "ada@example.com",
    password: str = "correct-horse-battery-staple",
) -> dict[str, Any]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return dict(response.json())


# --- Registration ---------------------------------------------------------


async def test_register_creates_user_without_leaking_password(db_client: AsyncClient) -> None:
    body = await _register(db_client)

    assert body["email"] == "ada@example.com"
    assert body["is_verified"] is False
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_email_returns_409(db_client: AsyncClient) -> None:
    await _register(db_client)

    response = await db_client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada@example.com",
            "password": "another-strong-password",
            "full_name": "Ada",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"


async def test_register_rejects_short_password(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "short1", "full_name": "Ada"},
    )

    assert response.status_code == 422


async def test_register_rejects_common_password(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/auth/register",
        json={"email": "common@example.com", "password": "password123", "full_name": "Ada"},
    )

    assert response.status_code == 422


async def test_register_normalises_email_case_for_uniqueness(db_client: AsyncClient) -> None:
    await _register(db_client, email="Ada@Example.com")

    response = await db_client.post(
        "/api/v1/auth/register",
        json={
            "email": "ada@example.com",
            "password": "another-strong-password",
            "full_name": "Ada",
        },
    )

    assert response.status_code == 409


# --- Login -----------------------------------------------------------------


async def test_login_returns_token_pair(db_client: AsyncClient) -> None:
    await _register(db_client)

    body = await _login(db_client)

    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 15 * 60


async def test_login_wrong_password_returns_generic_401(db_client: AsyncClient) -> None:
    await _register(db_client)

    response = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "totally-wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_login_nonexistent_email_returns_same_generic_error(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_account_locks_after_max_failed_attempts(db_client: AsyncClient) -> None:
    await _register(db_client)

    for _ in range(5):
        await db_client.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password"}
        )

    # Even the CORRECT password is now rejected - the account is locked, not just rate limited.
    response = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse-battery-staple"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_LOCKED"


# --- Refresh rotation & reuse detection (UC-02) -----------------------------


async def test_refresh_rotates_and_old_token_stops_working(db_client: AsyncClient) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    new_tokens = response.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    reuse_response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_refresh_token_reuse_revokes_the_whole_family(db_client: AsyncClient) -> None:
    """UC-02: presenting an already-rotated token is treated as theft - the entire family,
    including the token that replaced it, must be revoked."""
    await _register(db_client)
    tokens = await _login(db_client)

    rotated = (
        await db_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).json()

    # Reuse the original (already-rotated) token - triggers family-wide revocation.
    await db_client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    # The legitimate, newer token (issued by the rotation above) must now be dead too.
    response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


async def test_refresh_with_garbage_token_returns_401(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


# --- Logout ------------------------------------------------------------


async def test_logout_revokes_the_given_refresh_token(db_client: AsyncClient) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 204

    refresh_response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_response.status_code == 401


async def test_logout_without_token_revokes_every_session(db_client: AsyncClient) -> None:
    await _register(db_client)
    session_a = await _login(db_client)
    session_b = await _login(db_client)

    response = await db_client.post(
        "/api/v1/auth/logout",
        json={},
        headers={"Authorization": f"Bearer {session_a['access_token']}"},
    )
    assert response.status_code == 204

    for tokens in (session_a, session_b):
        refresh_response = await db_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refresh_response.status_code == 401


async def test_logout_requires_authentication(db_client: AsyncClient) -> None:
    response = await db_client.post("/api/v1/auth/logout", json={})

    assert response.status_code == 401


# --- Change password ------------------------------------------------------


async def test_change_password_requires_correct_current_password(db_client: AsyncClient) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "wrong-current-password",
            "new_password": "brand-new-password-123",
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CURRENT_PASSWORD"


async def test_change_password_succeeds_and_revokes_existing_sessions(
    db_client: AsyncClient,
) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "correct-horse-battery-staple",
            "new_password": "brand-new-password-123",
        },
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert response.status_code == 204

    # Old refresh token must be dead - password change revokes all sessions.
    stale_refresh = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert stale_refresh.status_code == 401

    # New password works; old one doesn't.
    assert (await _login(db_client, password="brand-new-password-123"))["access_token"]
    old_login = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse-battery-staple"},
    )
    assert old_login.status_code == 401


# --- Forgot / reset password ------------------------------------------------


async def test_forgot_password_responds_identically_for_unknown_email(
    db_client: AsyncClient,
) -> None:
    await _register(db_client)

    known = await db_client.post("/api/v1/auth/forgot-password", json={"email": "ada@example.com"})
    unknown = await db_client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content == b""


async def test_reset_password_with_valid_token_changes_password(
    db_client: AsyncClient, db_session: AsyncSession, db_settings: Settings
) -> None:
    await _register(db_client)
    auth_service = AuthService(db_session, db_settings)
    raw_token = await auth_service.request_password_reset(email="ada@example.com")
    assert raw_token is not None

    response = await db_client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": raw_token, "new_password": "post-reset-password-123"},
    )
    assert response.status_code == 204

    assert (await _login(db_client, password="post-reset-password-123"))["access_token"]


async def test_reset_password_token_is_single_use(
    db_client: AsyncClient, db_session: AsyncSession, db_settings: Settings
) -> None:
    await _register(db_client)
    auth_service = AuthService(db_session, db_settings)
    raw_token = await auth_service.request_password_reset(email="ada@example.com")
    assert raw_token is not None

    first = await db_client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": raw_token, "new_password": "post-reset-password-123"},
    )
    assert first.status_code == 204

    second = await db_client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": raw_token, "new_password": "another-password-456"},
    )
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "INVALID_OR_EXPIRED_RESET_TOKEN"


async def test_reset_password_with_bogus_token_returns_400(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": "not-a-real-token", "new_password": "post-reset-password-123"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_OR_EXPIRED_RESET_TOKEN"


async def test_reset_password_unlocks_a_locked_account(
    db_client: AsyncClient, db_session: AsyncSession, db_settings: Settings
) -> None:
    await _register(db_client)
    for _ in range(5):
        await db_client.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": "wrong-password"}
        )
    locked_attempt = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "ada@example.com", "password": "correct-horse-battery-staple"},
    )
    assert locked_attempt.status_code == 403

    auth_service = AuthService(db_session, db_settings)
    raw_token = await auth_service.request_password_reset(email="ada@example.com")
    assert raw_token is not None
    await db_client.post(
        "/api/v1/auth/reset-password",
        json={"reset_token": raw_token, "new_password": "post-reset-password-123"},
    )

    response = await _login(db_client, password="post-reset-password-123")
    assert response["access_token"]


# --- Profile ---------------------------------------------------------------


async def test_get_my_profile_requires_authentication(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/users/me")

    assert response.status_code == 401


async def test_get_my_profile_returns_the_caller(db_client: AsyncClient) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )

    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


async def test_update_my_profile_changes_allowed_fields(db_client: AsyncClient) -> None:
    await _register(db_client)
    tokens = await _login(db_client)

    response = await db_client.patch(
        "/api/v1/users/me",
        json={"full_name": "Ada, Countess of Lovelace"},
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Ada, Countess of Lovelace"


async def test_malformed_bearer_token_is_rejected(db_client: AsyncClient) -> None:
    response = await db_client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-jwt"}
    )

    assert response.status_code == 401


async def test_expired_access_token_is_rejected(
    db_client: AsyncClient, db_settings: Settings
) -> None:
    expired_token = create_access_token(
        user_id=1,
        role="USER",
        secret_key=db_settings.jwt_secret_key,
        algorithm=db_settings.jwt_algorithm,
        expires_minutes=-1,
    )

    response = await db_client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {expired_token}"}
    )

    assert response.status_code == 401
