from httpx import AsyncClient, Response

from tests.helpers import auth_headers, create_account, get_category_id


async def _create_rule(
    client: AsyncClient, headers: dict[str, str], *, account_id: int, **overrides: object
) -> Response:
    payload: dict[str, object] = {
        "account_id": account_id,
        "type": "EXPENSE",
        "amount": "25000.00",
        "currency": "INR",
        "description": "Rent",
        "frequency": "MONTHLY",
        "start_date": "2026-09-05",
        **overrides,
    }
    return await client.post("/api/v1/recurring-transactions", json=payload, headers=headers)


# --- Create --------------------------------------------------------------


async def test_create_rule(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)

    response = await _create_rule(db_client, headers, account_id=account["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "ACTIVE"
    assert body["next_run_date"] == "2026-09-05"
    assert body["interval"] == 1


async def test_create_rule_against_nonexistent_account_returns_404(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)

    response = await _create_rule(db_client, headers, account_id=999999)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_create_rule_with_category_type_mismatch_is_rejected(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    salary_id = await get_category_id(db_client, headers, name="Salary")

    response = await _create_rule(
        db_client, headers, account_id=account["id"], type="EXPENSE", category_id=salary_id
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CATEGORY_TYPE_MISMATCH"


async def test_create_rule_rejects_zero_interval(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)

    response = await _create_rule(db_client, headers, account_id=account["id"], interval=0)

    assert response.status_code == 422


# --- Update / pause / resume / delete --------------------------------------


async def test_update_rule_amount(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    rule = (await _create_rule(db_client, headers, account_id=account["id"])).json()

    response = await db_client.patch(
        f"/api/v1/recurring-transactions/{rule['id']}",
        json={"amount": "27000.00"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["amount"] == "27000.00"


async def test_pause_and_resume_rule(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    rule = (await _create_rule(db_client, headers, account_id=account["id"])).json()

    pause = await db_client.post(
        f"/api/v1/recurring-transactions/{rule['id']}/pause", headers=headers
    )
    assert pause.status_code == 204
    fetched = (
        await db_client.get(f"/api/v1/recurring-transactions/{rule['id']}", headers=headers)
    ).json()
    assert fetched["status"] == "PAUSED"

    resume = await db_client.post(
        f"/api/v1/recurring-transactions/{rule['id']}/resume", headers=headers
    )
    assert resume.status_code == 204
    fetched = (
        await db_client.get(f"/api/v1/recurring-transactions/{rule['id']}", headers=headers)
    ).json()
    assert fetched["status"] == "ACTIVE"


async def test_delete_rule_sets_status_ended(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    rule = (await _create_rule(db_client, headers, account_id=account["id"])).json()

    response = await db_client.delete(
        f"/api/v1/recurring-transactions/{rule['id']}", headers=headers
    )
    assert response.status_code == 204

    fetched = (
        await db_client.get(f"/api/v1/recurring-transactions/{rule['id']}", headers=headers)
    ).json()
    assert fetched["status"] == "ENDED"


async def test_cannot_pause_an_ended_rule(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    rule = (await _create_rule(db_client, headers, account_id=account["id"])).json()
    await db_client.delete(f"/api/v1/recurring-transactions/{rule['id']}", headers=headers)

    response = await db_client.post(
        f"/api/v1/recurring-transactions/{rule['id']}/pause", headers=headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "RECURRING_RULE_ENDED"


async def test_list_rules_filters_by_status(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    active = (await _create_rule(db_client, headers, account_id=account["id"])).json()
    paused = (
        await _create_rule(db_client, headers, account_id=account["id"], description="Gym")
    ).json()
    await db_client.post(f"/api/v1/recurring-transactions/{paused['id']}/pause", headers=headers)

    response = await db_client.get(
        "/api/v1/recurring-transactions", params={"status": "ACTIVE"}, headers=headers
    )

    ids = [r["id"] for r in response.json()]
    assert active["id"] in ids
    assert paused["id"] not in ids


# --- Upcoming occurrences --------------------------------------------------


async def test_upcoming_occurrences_does_not_materialize_transactions(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    rule = (
        await _create_rule(
            db_client, headers, account_id=account["id"], frequency="MONTHLY", interval=1
        )
    ).json()

    response = await db_client.get(
        f"/api/v1/recurring-transactions/{rule['id']}/occurrences",
        params={"upcoming": "true"},
        headers=headers,
    )

    assert response.status_code == 200
    dates = [item["scheduled_date"] for item in response.json()]
    assert dates == ["2026-09-05", "2026-10-05", "2026-11-05", "2026-12-05", "2027-01-05"]

    # No transactions were actually created.
    txns = (await db_client.get("/api/v1/transactions", headers=headers)).json()
    assert txns["total"] == 0


# --- Cross-user isolation ---------------------------------------------------


async def test_cannot_view_another_users_rule(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    account = await create_account(db_client, owner)
    rule = (await _create_rule(db_client, owner, account_id=account["id"])).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/recurring-transactions/{rule['id']}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RECURRING_RULE_NOT_FOUND"


async def test_cannot_pause_another_users_rule(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    account = await create_account(db_client, owner)
    rule = (await _create_rule(db_client, owner, account_id=account["id"])).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(
        f"/api/v1/recurring-transactions/{rule['id']}/pause", headers=intruder
    )

    assert response.status_code == 404
    still_active = (
        await db_client.get(f"/api/v1/recurring-transactions/{rule['id']}", headers=owner)
    ).json()
    assert still_active["status"] == "ACTIVE"
