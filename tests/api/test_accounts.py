from httpx import AsyncClient

from tests.helpers import auth_headers


async def _create_account(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "HDFC Salary Account",
        "type": "BANK",
        "currency": "INR",
        "opening_balance": "1000.00",
        **overrides,
    }
    response = await client.post("/api/v1/accounts", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- Create ------------------------------------------------------------


async def test_create_account_returns_account_with_opening_balance(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    account = await _create_account(db_client, headers)

    assert account["name"] == "HDFC Salary Account"
    assert account["type"] == "BANK"
    assert account["currency"] == "INR"
    assert account["balance"] == "1000.00"
    assert account["is_archived"] is False
    assert account["allow_negative_balance"] is False


async def test_create_credit_card_account_defaults_to_allowing_negative_balance(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)

    account = await _create_account(db_client, headers, type="CREDIT_CARD", name="Visa")

    assert account["allow_negative_balance"] is True


async def test_create_account_defaults_opening_balance_to_zero(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.post(
        "/api/v1/accounts",
        json={"name": "Cash Wallet", "type": "CASH", "currency": "INR"},
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["balance"] == "0.00"


async def test_create_account_rejects_invalid_currency(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.post(
        "/api/v1/accounts",
        json={"name": "Bad Currency", "type": "CASH", "currency": "US"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_account_rejects_invalid_type(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.post(
        "/api/v1/accounts",
        json={"name": "Bad Type", "type": "CRYPTO_WALLET", "currency": "INR"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_account_requires_authentication(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/accounts",
        json={"name": "No Auth", "type": "CASH", "currency": "INR"},
    )

    assert response.status_code == 401


# --- List ----------------------------------------------------------------


async def test_list_accounts_excludes_archived_by_default(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    active = await _create_account(db_client, headers, name="Active")
    archived = await _create_account(db_client, headers, name="ToArchive")
    await db_client.post(f"/api/v1/accounts/{archived['id']}/archive", headers=headers)

    response = await db_client.get("/api/v1/accounts", headers=headers)

    assert response.status_code == 200
    ids = [a["id"] for a in response.json()]
    assert active["id"] in ids
    assert archived["id"] not in ids


async def test_list_accounts_includes_archived_when_requested(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    archived = await _create_account(db_client, headers, name="ToArchive")
    await db_client.post(f"/api/v1/accounts/{archived['id']}/archive", headers=headers)

    response = await db_client.get(
        "/api/v1/accounts", params={"include_archived": "true"}, headers=headers
    )

    assert response.status_code == 200
    ids = [a["id"] for a in response.json()]
    assert archived["id"] in ids


async def test_list_accounts_only_returns_the_caller_own_accounts(db_client: AsyncClient) -> None:
    owner_headers = await auth_headers(db_client, email="owner@example.com")
    await _create_account(db_client, owner_headers, name="Owner Account")
    other_headers = await auth_headers(db_client, email="other@example.com")
    await _create_account(db_client, other_headers, name="Other Account")

    response = await db_client.get("/api/v1/accounts", headers=other_headers)

    names = [a["name"] for a in response.json()]
    assert names == ["Other Account"]


# --- Retrieve / update / archive ----------------------------------------


async def test_get_account_returns_the_account(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = await _create_account(db_client, headers)

    response = await db_client.get(f"/api/v1/accounts/{created['id']}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_nonexistent_account_returns_404(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get("/api/v1/accounts/999999", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_update_account_changes_name(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = await _create_account(db_client, headers)

    response = await db_client.patch(
        f"/api/v1/accounts/{created['id']}", json={"name": "Renamed"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert response.json()["currency"] == "INR"  # unchanged - currency is immutable


async def test_archive_account_excludes_it_from_default_listing(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = await _create_account(db_client, headers)

    response = await db_client.post(f"/api/v1/accounts/{created['id']}/archive", headers=headers)

    assert response.status_code == 204
    fetched = await db_client.get(f"/api/v1/accounts/{created['id']}", headers=headers)
    assert fetched.json()["is_archived"] is True


async def test_archiving_twice_is_idempotent(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = await _create_account(db_client, headers)

    first = await db_client.post(f"/api/v1/accounts/{created['id']}/archive", headers=headers)
    second = await db_client.post(f"/api/v1/accounts/{created['id']}/archive", headers=headers)

    assert first.status_code == second.status_code == 204


async def test_get_account_balance(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    created = await _create_account(db_client, headers, opening_balance="2500.50")

    response = await db_client.get(f"/api/v1/accounts/{created['id']}/balance", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["account_id"] == created["id"]
    assert body["balance"] == "2500.50"
    assert body["currency"] == "INR"


# --- Cross-user isolation (security-architecture.md §2) -------------------


async def test_cannot_view_another_users_account(db_client: AsyncClient) -> None:
    owner_headers = await auth_headers(db_client, email="owner@example.com")
    owned = await _create_account(db_client, owner_headers)
    intruder_headers = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/accounts/{owned['id']}", headers=intruder_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_cannot_update_another_users_account(db_client: AsyncClient) -> None:
    owner_headers = await auth_headers(db_client, email="owner@example.com")
    owned = await _create_account(db_client, owner_headers)
    intruder_headers = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.patch(
        f"/api/v1/accounts/{owned['id']}", json={"name": "Hijacked"}, headers=intruder_headers
    )

    assert response.status_code == 404


async def test_cannot_archive_another_users_account(db_client: AsyncClient) -> None:
    owner_headers = await auth_headers(db_client, email="owner@example.com")
    owned = await _create_account(db_client, owner_headers)
    intruder_headers = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(
        f"/api/v1/accounts/{owned['id']}/archive", headers=intruder_headers
    )

    assert response.status_code == 404

    # And it really wasn't archived - the owner still sees it active.
    still_active = await db_client.get(f"/api/v1/accounts/{owned['id']}", headers=owner_headers)
    assert still_active.json()["is_archived"] is False


async def test_cannot_view_another_users_account_balance(db_client: AsyncClient) -> None:
    owner_headers = await auth_headers(db_client, email="owner@example.com")
    owned = await _create_account(db_client, owner_headers)
    intruder_headers = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(
        f"/api/v1/accounts/{owned['id']}/balance", headers=intruder_headers
    )

    assert response.status_code == 404
