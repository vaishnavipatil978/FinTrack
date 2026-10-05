from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import UserRole
from app.models.user import User
from tests.helpers import DEFAULT_PASSWORD, auth_headers, login, register


async def _promote_to_admin(db_session: AsyncSession, email: str) -> int:
    user = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    user.role = UserRole.ADMIN
    await db_session.commit()
    return user.id


async def _admin_headers(client: AsyncClient, email: str) -> dict[str, str]:
    tokens = await login(client, email=email)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_non_admin_cannot_list_users(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client, email="plain@example.com")

    response = await db_client.get("/api/v1/admin/users", headers=headers)

    assert response.status_code == 403


async def test_admin_can_list_users(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await register(db_client, email="admin@example.com", full_name="Admin One")
    await _promote_to_admin(db_session, "admin@example.com")
    await register(db_client, email="member@example.com", full_name="Member")
    admin_headers = await _admin_headers(db_client, "admin@example.com")

    response = await db_client.get("/api/v1/admin/users", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    emails = {item["email"] for item in body["items"]}
    assert "admin@example.com" in emails
    assert "member@example.com" in emails
    assert body["total"] >= 2


async def test_admin_can_filter_and_search_users(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(db_client, email="admin2@example.com", full_name="Admin Two")
    await _promote_to_admin(db_session, "admin2@example.com")
    admin_headers = await _admin_headers(db_client, "admin2@example.com")
    await register(db_client, email="findme@example.com", full_name="Findable Person")

    response = await db_client.get(
        "/api/v1/admin/users", params={"search": "Findable"}, headers=admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["email"] == "findme@example.com"


async def test_admin_can_lock_and_unlock_user(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(db_client, email="admin3@example.com", full_name="Admin Three")
    await _promote_to_admin(db_session, "admin3@example.com")
    admin_headers = await _admin_headers(db_client, "admin3@example.com")
    target = await register(db_client, email="target@example.com", full_name="Target User")
    target_id = target["id"]

    lock_response = await db_client.post(
        f"/api/v1/admin/users/{target_id}/lock", headers=admin_headers
    )
    assert lock_response.status_code == 204

    blocked_login = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": DEFAULT_PASSWORD},
    )
    assert blocked_login.status_code in (401, 403)

    repeat_lock = await db_client.post(
        f"/api/v1/admin/users/{target_id}/lock", headers=admin_headers
    )
    assert repeat_lock.status_code == 204

    unlock_response = await db_client.post(
        f"/api/v1/admin/users/{target_id}/unlock", headers=admin_headers
    )
    assert unlock_response.status_code == 204

    allowed_login = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "target@example.com", "password": DEFAULT_PASSWORD},
    )
    assert allowed_login.status_code == 200

    repeat_unlock = await db_client.post(
        f"/api/v1/admin/users/{target_id}/unlock", headers=admin_headers
    )
    assert repeat_unlock.status_code == 204


async def test_admin_cannot_lock_self(db_client: AsyncClient, db_session: AsyncSession) -> None:
    admin_data = await register(db_client, email="admin4@example.com", full_name="Admin Four")
    await _promote_to_admin(db_session, "admin4@example.com")
    admin_headers = await _admin_headers(db_client, "admin4@example.com")

    response = await db_client.post(
        f"/api/v1/admin/users/{admin_data['id']}/lock", headers=admin_headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "CANNOT_LOCK_SELF"


async def test_lock_revokes_existing_sessions(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    await register(db_client, email="admin5@example.com", full_name="Admin Five")
    await _promote_to_admin(db_session, "admin5@example.com")
    admin_headers = await _admin_headers(db_client, "admin5@example.com")
    target = await register(db_client, email="target2@example.com", full_name="Target Two")
    target_tokens = await login(db_client, email="target2@example.com")

    await db_client.post(f"/api/v1/admin/users/{target['id']}/lock", headers=admin_headers)

    refresh_response = await db_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": target_tokens["refresh_token"]}
    )
    assert refresh_response.status_code in (401, 403)


async def test_admin_can_view_audit_logs(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await register(db_client, email="admin6@example.com", full_name="Admin Six")
    await _promote_to_admin(db_session, "admin6@example.com")
    admin_headers = await _admin_headers(db_client, "admin6@example.com")
    target = await register(db_client, email="target3@example.com", full_name="Target Three")
    await db_client.post(f"/api/v1/admin/users/{target['id']}/lock", headers=admin_headers)

    response = await db_client.get("/api/v1/admin/audit", headers=admin_headers)

    assert response.status_code == 200, response.text
    actions = {item["action"] for item in response.json()["items"]}
    assert "ADMIN_USER_LOCKED" in actions


async def test_non_admin_cannot_access_admin_audit(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client, email="plain2@example.com")

    response = await db_client.get("/api/v1/admin/audit", headers=headers)

    assert response.status_code == 403
