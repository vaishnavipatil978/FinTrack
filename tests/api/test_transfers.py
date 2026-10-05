from httpx import AsyncClient, Response

from tests.helpers import auth_headers, create_account


async def _create_transfer(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    from_account_id: int,
    to_account_id: int,
    **overrides: object,
) -> Response:
    payload: dict[str, object] = {
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "amount": "100.00",
        "currency": "INR",
        "transfer_date": "2026-09-01",
        **overrides,
    }
    response = await client.post("/api/v1/transfers", json=payload, headers=headers)
    return response


async def _balance(client: AsyncClient, headers: dict[str, str], account_id: int) -> str:
    response = await client.get(f"/api/v1/accounts/{account_id}/balance", headers=headers)
    return str(response.json()["balance"])


# --- Happy path --------------------------------------------------------


async def test_transfer_debits_source_and_credits_destination(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(db_client, headers, name="Source", opening_balance="1000.00")
    dst = await create_account(db_client, headers, name="Dest", opening_balance="0.00")

    response = await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"], amount="300.00"
    )

    assert response.status_code == 201, response.text
    assert await _balance(db_client, headers, src["id"]) == "700.00"
    assert await _balance(db_client, headers, dst["id"]) == "300.00"


async def test_transfer_creates_two_linked_transaction_legs(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(db_client, headers, name="Source", opening_balance="1000.00")
    dst = await create_account(db_client, headers, name="Dest")

    await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"], amount="300.00"
    )

    src_txns = (
        await db_client.get(
            "/api/v1/transactions", params={"account_id": src["id"]}, headers=headers
        )
    ).json()["items"]
    dst_txns = (
        await db_client.get(
            "/api/v1/transactions", params={"account_id": dst["id"]}, headers=headers
        )
    ).json()["items"]
    assert src_txns[0]["type"] == "TRANSFER_OUT"
    assert dst_txns[0]["type"] == "TRANSFER_IN"
    assert src_txns[0]["amount"] == dst_txns[0]["amount"] == "300.00"


# --- Validation ----------------------------------------------------------


async def test_transfer_to_same_account_is_rejected(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)

    response = await _create_transfer(
        db_client, headers, from_account_id=account["id"], to_account_id=account["id"]
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SAME_ACCOUNT_TRANSFER"


async def test_transfer_between_different_currencies_is_rejected(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(db_client, headers, name="INR Account", currency="INR")
    dst = await create_account(db_client, headers, name="USD Account", currency="USD")

    response = await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CURRENCY_MISMATCH"


async def test_transfer_exceeding_balance_is_rejected_for_non_credit_account(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(db_client, headers, name="Source", opening_balance="50.00")
    dst = await create_account(db_client, headers, name="Dest", opening_balance="0.00")

    response = await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"], amount="500.00"
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INSUFFICIENT_FUNDS"
    # Balances must be untouched by a rejected transfer.
    assert await _balance(db_client, headers, src["id"]) == "50.00"
    assert await _balance(db_client, headers, dst["id"]) == "0.00"


async def test_transfer_exceeding_balance_is_allowed_for_credit_card_source(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(
        db_client, headers, name="Visa", type="CREDIT_CARD", opening_balance="0.00"
    )
    dst = await create_account(db_client, headers, name="Dest")

    response = await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"], amount="500.00"
    )

    assert response.status_code == 201
    assert await _balance(db_client, headers, src["id"]) == "-500.00"


async def test_transfer_from_or_to_archived_account_is_rejected(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    src = await create_account(db_client, headers, name="Source")
    dst = await create_account(db_client, headers, name="Dest")
    await db_client.post(f"/api/v1/accounts/{dst['id']}/archive", headers=headers)

    response = await _create_transfer(
        db_client, headers, from_account_id=src["id"], to_account_id=dst["id"]
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ACCOUNT_ARCHIVED"


async def test_transfer_requires_authentication(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/transfers",
        json={
            "from_account_id": 1,
            "to_account_id": 2,
            "amount": "10.00",
            "currency": "INR",
            "transfer_date": "2026-09-01",
        },
    )

    assert response.status_code == 401


# --- Cross-user isolation ---------------------------------------------------


async def test_cannot_transfer_from_another_users_account(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    owner_account = await create_account(db_client, owner, name="Owner Source")
    intruder = await auth_headers(db_client, email="intruder@example.com")
    intruder_account = await create_account(db_client, intruder, name="Intruder Dest")

    response = await _create_transfer(
        db_client,
        intruder,
        from_account_id=owner_account["id"],
        to_account_id=intruder_account["id"],
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"
    # And the owner's balance is untouched.
    assert await _balance(db_client, owner, owner_account["id"]) == "1000.00"


async def test_cannot_view_another_users_transfer(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    src = await create_account(db_client, owner, name="Source")
    dst = await create_account(db_client, owner, name="Dest")
    created = (
        await _create_transfer(db_client, owner, from_account_id=src["id"], to_account_id=dst["id"])
    ).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/transfers/{created['id']}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRANSFER_NOT_FOUND"


async def test_list_transfers_only_returns_the_callers_own(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    src = await create_account(db_client, owner, name="Source")
    dst = await create_account(db_client, owner, name="Dest")
    await _create_transfer(db_client, owner, from_account_id=src["id"], to_account_id=dst["id"])
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get("/api/v1/transfers", headers=intruder)

    assert response.json()["items"] == []
