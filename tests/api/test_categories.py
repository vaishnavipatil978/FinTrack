from httpx import AsyncClient

from tests.helpers import auth_headers


async def test_list_categories_includes_seeded_system_categories(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get("/api/v1/categories", headers=headers)

    assert response.status_code == 200
    names = {c["name"] for c in response.json()}
    assert "Food" in names
    assert "Salary" in names
    assert all(c["is_system"] for c in response.json() if c["name"] == "Food")


async def test_list_categories_filters_by_type(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get("/api/v1/categories", params={"type": "INCOME"}, headers=headers)

    assert response.status_code == 200
    assert all(c["type"] == "INCOME" for c in response.json())


async def test_create_custom_category(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.post(
        "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=headers
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Pet Care"
    assert body["is_system"] is False


async def test_create_duplicate_category_name_for_same_user_returns_409(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    await db_client.post(
        "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=headers
    )

    response = await db_client.post(
        "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CATEGORY_NAME_EXISTS"


async def test_two_different_users_can_share_a_custom_category_name(
    db_client: AsyncClient,
) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    other = await auth_headers(db_client, email="other@example.com")
    await db_client.post(
        "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=owner
    )

    response = await db_client.post(
        "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=other
    )

    assert response.status_code == 201


async def test_cannot_modify_a_system_category(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    categories = (await db_client.get("/api/v1/categories", headers=headers)).json()
    food = next(c for c in categories if c["name"] == "Food")

    response = await db_client.patch(
        f"/api/v1/categories/{food['id']}", json={"name": "Renamed Food"}, headers=headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CANNOT_MODIFY_SYSTEM_CATEGORY"


async def test_cannot_archive_a_system_category(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    categories = (await db_client.get("/api/v1/categories", headers=headers)).json()
    food = next(c for c in categories if c["name"] == "Food")

    response = await db_client.post(f"/api/v1/categories/{food['id']}/archive", headers=headers)

    assert response.status_code == 403


async def test_can_archive_own_custom_category(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = (
        await db_client.post(
            "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=headers
        )
    ).json()

    response = await db_client.post(f"/api/v1/categories/{created['id']}/archive", headers=headers)
    assert response.status_code == 204

    default_list = (await db_client.get("/api/v1/categories", headers=headers)).json()
    assert created["id"] not in [c["id"] for c in default_list]


async def test_cannot_modify_another_users_custom_category(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    created = (
        await db_client.post(
            "/api/v1/categories", json={"name": "Pet Care", "type": "EXPENSE"}, headers=owner
        )
    ).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.patch(
        f"/api/v1/categories/{created['id']}", json={"name": "Hijacked"}, headers=intruder
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CATEGORY_NOT_FOUND"
