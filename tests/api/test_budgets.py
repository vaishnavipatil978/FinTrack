from httpx import AsyncClient, Response

from tests.helpers import auth_headers, create_account, create_transaction, get_category_id


async def _create_budget(
    client: AsyncClient, headers: dict[str, str], *, category_id: int, **overrides: object
) -> Response:
    payload: dict[str, object] = {
        "category_id": category_id,
        "target_amount": "15000.00",
        "currency": "INR",
        "period_month": 9,
        "period_year": 2026,
        **overrides,
    }
    response = await client.post("/api/v1/budgets", json=payload, headers=headers)
    return response


# --- Create ------------------------------------------------------------


async def test_create_budget(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")

    response = await _create_budget(db_client, headers, category_id=category_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["target_amount"] == "15000.00"
    assert body["spent"] == "0.00"
    assert body["remaining"] == "15000.00"
    assert body["utilization_pct"] == "0.00"
    assert body["is_overspent"] is False


async def test_duplicate_budget_for_same_category_and_period_returns_409(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id)

    response = await _create_budget(db_client, headers, category_id=category_id)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUDGET_ALREADY_EXISTS"


async def test_same_category_different_period_is_allowed(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id, period_month=9)

    response = await _create_budget(db_client, headers, category_id=category_id, period_month=10)

    assert response.status_code == 201


async def test_budget_on_income_category_is_rejected(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Salary")

    response = await _create_budget(db_client, headers, category_id=category_id)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CATEGORY_TYPE_MISMATCH"


async def test_create_budget_rejects_invalid_month(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")

    response = await _create_budget(db_client, headers, category_id=category_id, period_month=13)

    assert response.status_code == 422


# --- Live utilization computation (UC-06) -----------------------------


async def test_spent_reflects_matching_expense_transactions(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id)
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        amount="4500.00",
        transaction_date="2026-09-05",
    )
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        amount="7000.00",
        transaction_date="2026-09-15",
    )

    response = await db_client.get(
        "/api/v1/budgets", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    budget = response.json()[0]
    assert budget["spent"] == "11500.00"
    assert budget["remaining"] == "3500.00"
    assert budget["utilization_pct"] == "76.67"
    assert budget["is_overspent"] is False


async def test_overspending_is_flagged(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id, target_amount="1000.00")
    await create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="1500.00"
    )

    response = await db_client.get(
        "/api/v1/budgets", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    budget = response.json()[0]
    assert budget["is_overspent"] is True
    assert budget["remaining"] == "-500.00"


async def test_income_transactions_do_not_count_as_spend(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    food_id = await get_category_id(db_client, headers, name="Food")
    salary_id = await get_category_id(db_client, headers, name="Salary")
    await _create_budget(db_client, headers, category_id=food_id)
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=salary_id,
        type="INCOME",
        amount="50000.00",
    )

    response = await db_client.get(
        "/api/v1/budgets", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    assert response.json()[0]["spent"] == "0.00"


async def test_voided_transactions_are_excluded_from_spend(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id)
    txn = await create_transaction(
        db_client, headers, account_id=account["id"], category_id=category_id, amount="500.00"
    )
    await db_client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)

    response = await db_client.get(
        "/api/v1/budgets", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    assert response.json()[0]["spent"] == "0.00"


async def test_transactions_outside_the_period_are_excluded(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    category_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, category_id=category_id, period_month=9)
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=category_id,
        amount="500.00",
        transaction_date="2026-10-01",  # next month
    )

    response = await db_client.get(
        "/api/v1/budgets", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    assert response.json()[0]["spent"] == "0.00"


# --- Update / delete ---------------------------------------------------


async def test_update_budget_target_amount(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")
    created = (await _create_budget(db_client, headers, category_id=category_id)).json()

    response = await db_client.patch(
        f"/api/v1/budgets/{created['id']}", json={"target_amount": "20000.00"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["target_amount"] == "20000.00"


async def test_delete_budget(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    category_id = await get_category_id(db_client, headers, name="Food")
    created = (await _create_budget(db_client, headers, category_id=category_id)).json()

    response = await db_client.delete(f"/api/v1/budgets/{created['id']}", headers=headers)
    assert response.status_code == 204

    fetch = await db_client.get(f"/api/v1/budgets/{created['id']}", headers=headers)
    assert fetch.status_code == 404


# --- Summary -------------------------------------------------------------


async def test_budget_summary_aggregates_across_categories(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    food_id = await get_category_id(db_client, headers, name="Food")
    transport_id = await get_category_id(db_client, headers, name="Transport")
    await _create_budget(db_client, headers, category_id=food_id, target_amount="10000.00")
    await _create_budget(db_client, headers, category_id=transport_id, target_amount="5000.00")
    await create_transaction(
        db_client, headers, account_id=account["id"], category_id=food_id, amount="3000.00"
    )
    await create_transaction(
        db_client, headers, account_id=account["id"], category_id=transport_id, amount="1000.00"
    )

    response = await db_client.get(
        "/api/v1/budgets/summary", params={"period_month": 9, "period_year": 2026}, headers=headers
    )

    body = response.json()
    assert body["total_budgeted"] == "15000.00"
    assert body["total_spent"] == "4000.00"
    assert len(body["categories"]) == 2


# --- Cross-user isolation ---------------------------------------------------


async def test_cannot_view_another_users_budget(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    category_id = await get_category_id(db_client, owner, name="Food")
    created = (await _create_budget(db_client, owner, category_id=category_id)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/budgets/{created['id']}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BUDGET_NOT_FOUND"


async def test_cannot_update_another_users_budget(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    category_id = await get_category_id(db_client, owner, name="Food")
    created = (await _create_budget(db_client, owner, category_id=category_id)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.patch(
        f"/api/v1/budgets/{created['id']}", json={"target_amount": "1.00"}, headers=intruder
    )

    assert response.status_code == 404


async def test_cannot_delete_another_users_budget(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    category_id = await get_category_id(db_client, owner, name="Food")
    created = (await _create_budget(db_client, owner, category_id=category_id)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.delete(f"/api/v1/budgets/{created['id']}", headers=intruder)

    assert response.status_code == 404
    still_there = await db_client.get(f"/api/v1/budgets/{created['id']}", headers=owner)
    assert still_there.status_code == 200
