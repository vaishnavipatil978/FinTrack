from httpx import AsyncClient

from tests.helpers import auth_headers, create_account, get_category_id


async def _create_transaction(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    account_id: int,
    category_id: int,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "account_id": account_id,
        "type": "EXPENSE",
        "amount": "100.00",
        "currency": "INR",
        "category_id": category_id,
        "transaction_date": "2026-09-01",
        "description": "Groceries",
        **overrides,
    }
    response = await client.post("/api/v1/transactions", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


# --- Create + balance effect ------------------------------------------------


async def test_create_expense_debits_the_account(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Food")

    await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="150.00"
    )

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "850.00"


async def test_create_income_credits_the_account(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Salary")

    await _create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        type="INCOME",
        amount="5000.00",
        description="Paycheck",
    )

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "6000.00"


async def test_create_transaction_against_nonexistent_account_returns_404(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")

    response = await db_client.post(
        "/api/v1/transactions",
        json={
            "account_id": 999999,
            "type": "EXPENSE",
            "amount": "10.00",
            "currency": "INR",
            "category_id": category_id,
            "transaction_date": "2026-09-01",
            "description": "x",
        },
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_create_transaction_against_archived_account_is_rejected(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await db_client.post(f"/api/v1/accounts/{account['id']}/archive", headers=headers)

    response = await db_client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "10.00",
            "currency": "INR",
            "category_id": category_id,
            "transaction_date": "2026-09-01",
            "description": "x",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ACCOUNT_ARCHIVED"


async def test_create_transaction_with_mismatched_category_type_is_rejected(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    income_category_id = await get_category_id(db_client, headers, name="Salary")

    response = await db_client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "10.00",
            "currency": "INR",
            "category_id": income_category_id,
            "transaction_date": "2026-09-01",
            "description": "x",
        },
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CATEGORY_TYPE_MISMATCH"


async def test_create_transaction_rejects_zero_amount(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")

    response = await db_client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "0.00",
            "currency": "INR",
            "category_id": category_id,
            "transaction_date": "2026-09-01",
            "description": "x",
        },
        headers=headers,
    )

    assert response.status_code == 422


# --- Update (reverse-then-apply balance semantics) --------------------------


async def test_update_transaction_amount_adjusts_balance_by_the_difference_only(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Food")
    txn = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="100.00"
    )

    response = await db_client.patch(
        f"/api/v1/transactions/{txn['id']}", json={"amount": "300.00"}, headers=headers
    )
    assert response.status_code == 200

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "700.00"  # 1000 - 300, not 1000 - 100 - 300


async def test_update_transaction_description_does_not_affect_balance(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Food")
    txn = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="100.00"
    )

    await db_client.patch(
        f"/api/v1/transactions/{txn['id']}", json={"description": "Renamed"}, headers=headers
    )

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "900.00"


# --- Delete (void) -----------------------------------------------------


async def test_delete_transaction_reverses_its_balance_effect(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Food")
    txn = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="250.00"
    )

    response = await db_client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)
    assert response.status_code == 204

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "1000.00"


async def test_voided_transaction_cannot_be_edited(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    txn = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id
    )
    await db_client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)

    response = await db_client.patch(
        f"/api/v1/transactions/{txn['id']}", json={"amount": "1.00"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TRANSACTION_VOIDED"


async def test_deleting_twice_is_idempotent_and_does_not_double_reverse(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="1000.00")
    category_id = await get_category_id(db_client, headers, name="Food")
    txn = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="250.00"
    )

    first = await db_client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)
    second = await db_client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)
    assert first.status_code == second.status_code == 204

    balance = await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    assert balance.json()["balance"] == "1000.00"  # not 1250 (double-reversed)


async def test_voided_transaction_is_excluded_from_default_list(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    kept = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, description="Kept"
    )
    voided = await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, description="Voided"
    )
    await db_client.delete(f"/api/v1/transactions/{voided['id']}", headers=headers)

    response = await db_client.get("/api/v1/transactions", headers=headers)

    ids = [t["id"] for t in response.json()["items"]]
    assert kept["id"] in ids
    assert voided["id"] not in ids


# --- List: filtering, sorting, pagination -----------------------------------


async def test_list_transactions_filters_by_account_and_date_range(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account_a = await create_account(db_client, headers, name="A")
    account_b = await create_account(db_client, headers, name="B")
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_transaction(
        db_client,
        headers,
        account_id=account_a["id"],
        category_id=category_id,
        transaction_date="2026-01-15",
        description="InRange",
    )
    await _create_transaction(
        db_client,
        headers,
        account_id=account_a["id"],
        category_id=category_id,
        transaction_date="2026-03-01",
        description="OutOfRange",
    )
    await _create_transaction(
        db_client,
        headers,
        account_id=account_b["id"],
        category_id=category_id,
        description="OtherAccount",
    )

    response = await db_client.get(
        "/api/v1/transactions",
        params={
            "account_id": account_a["id"],
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
        },
        headers=headers,
    )

    descriptions = [t["description"] for t in response.json()["items"]]
    assert descriptions == ["InRange"]


async def test_list_transactions_search_matches_description(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        description="Amazon order",
    )
    await _create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        description="Grocery run",
    )

    response = await db_client.get(
        "/api/v1/transactions", params={"search": "amazon"}, headers=headers
    )

    descriptions = [t["description"] for t in response.json()["items"]]
    assert descriptions == ["Amazon order"]


async def test_list_transactions_pagination(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    for i in range(5):
        await _create_transaction(
            db_client,
            headers,
            account_id=account["id"],
            category_id=category_id,
            description=f"Txn {i}",
            transaction_date=f"2026-01-{i + 1:02d}",
        )

    response = await db_client.get(
        "/api/v1/transactions", params={"page": 1, "page_size": 2}, headers=headers
    )

    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 5
    assert body["total_pages"] == 3


async def test_list_transactions_sorted_by_amount_ascending(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="50.00"
    )
    await _create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="10.00"
    )

    response = await db_client.get(
        "/api/v1/transactions",
        params={"sort_by": "amount", "sort_dir": "asc"},
        headers=headers,
    )

    amounts = [t["amount"] for t in response.json()["items"]]
    assert amounts == ["10.00", "50.00"]


# --- Cross-user isolation ---------------------------------------------------


async def test_cannot_view_another_users_transaction(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    account = await create_account(db_client, owner)
    category_id = await get_category_id(db_client, owner, name="Food")
    txn = await _create_transaction(
        db_client, owner, account_id=account["id"], category_id=category_id
    )
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/transactions/{txn['id']}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TRANSACTION_NOT_FOUND"


async def test_cannot_create_transaction_against_another_users_account(
    db_client: AsyncClient,
) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    account = await create_account(db_client, owner)
    intruder = await auth_headers(db_client, email="intruder@example.com")
    category_id = await get_category_id(db_client, intruder, name="Food")

    response = await db_client.post(
        "/api/v1/transactions",
        json={
            "account_id": account["id"],
            "type": "EXPENSE",
            "amount": "10.00",
            "currency": "INR",
            "category_id": category_id,
            "transaction_date": "2026-09-01",
            "description": "Hijack attempt",
        },
        headers=intruder,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_list_transactions_only_returns_the_callers_own(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    owner_account = await create_account(db_client, owner)
    owner_category = await get_category_id(db_client, owner, name="Food")
    await _create_transaction(
        db_client, owner, account_id=owner_account["id"], category_id=owner_category
    )
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get("/api/v1/transactions", headers=intruder)

    assert response.json()["items"] == []
