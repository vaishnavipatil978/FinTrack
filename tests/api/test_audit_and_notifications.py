from httpx import AsyncClient

from tests.helpers import auth_headers, create_account, create_transaction, get_category_id


async def _audit_actions(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("/api/v1/audit/me", params={"page_size": 100}, headers=headers)
    assert response.status_code == 200, response.text
    return [item["action"] for item in response.json()["items"]]


async def _create_budget(
    client: AsyncClient, headers: dict[str, str], category_id: int, target: str
) -> None:
    response = await client.post(
        "/api/v1/budgets",
        json={
            "category_id": category_id,
            "target_amount": target,
            "currency": "INR",
            "period_month": 9,
            "period_year": 2026,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text


async def _create_goal(
    client: AsyncClient, headers: dict[str, str], target: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/goals",
        json={
            "name": "Trip",
            "target_amount": target,
            "currency": "INR",
            "target_date": "2099-12-31",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _seed_goal_achieved(client: AsyncClient, headers: dict[str, str]) -> None:
    goal = await _create_goal(client, headers, "100.00")
    await client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "100.00", "contributed_at": "2026-09-01"},
        headers=headers,
    )


# --- Audit trail ---------------------------------------------------------


async def test_writes_produce_audit_entries(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers)
    food_id = await get_category_id(db_client, headers, name="Food")
    await create_transaction(db_client, headers, account_id=account["id"], category_id=food_id)

    actions = await _audit_actions(db_client, headers)

    assert "USER_REGISTERED" in actions
    assert "LOGIN" in actions
    assert "ACCOUNT_CREATED" in actions
    assert "TRANSACTION_CREATED" in actions


async def test_audit_entries_never_contain_secrets(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await db_client.get("/api/v1/audit/me", headers=headers)

    body = response.text
    assert "correct-horse-battery-staple" not in body
    assert "hashed_password" not in body
    assert "refresh_token" not in body


async def test_audit_trail_is_scoped_to_the_caller(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    await create_account(db_client, owner)
    intruder = await auth_headers(db_client, email="intruder@example.com")

    actions = await _audit_actions(db_client, intruder)

    assert "ACCOUNT_CREATED" not in actions


async def test_audit_can_be_filtered_by_action(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers)

    response = await db_client.get(
        "/api/v1/audit/me", params={"action": "ACCOUNT_CREATED"}, headers=headers
    )

    assert {item["action"] for item in response.json()["items"]} == {"ACCOUNT_CREATED"}


# --- Notification triggers -----------------------------------------------


async def test_crossing_a_budget_notifies_exactly_once(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, opening_balance="10000.00")
    food_id = await get_category_id(db_client, headers, name="Food")
    await _create_budget(db_client, headers, food_id, "1000.00")

    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=food_id,
        amount="600.00",
        transaction_date="2026-09-02",
    )
    # This one crosses the 1000 line.
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=food_id,
        amount="600.00",
        transaction_date="2026-09-03",
    )
    # Already over budget - must not notify again.
    await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=food_id,
        amount="100.00",
        transaction_date="2026-09-04",
    )

    response = await db_client.get(
        "/api/v1/notifications", params={"page_size": 100}, headers=headers
    )
    types = [n["type"] for n in response.json()["items"]]
    assert types.count("BUDGET_EXCEEDED") == 1


async def test_reaching_a_goal_target_notifies(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await _seed_goal_achieved(db_client, headers)

    response = await db_client.get("/api/v1/notifications", headers=headers)

    assert "GOAL_ACHIEVED" in [n["type"] for n in response.json()["items"]]


# --- Read state and preferences -----------------------------------------


async def test_unread_filter_and_mark_read(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await _seed_goal_achieved(db_client, headers)
    listing = (await db_client.get("/api/v1/notifications", headers=headers)).json()
    notification_id = listing["items"][0]["id"]

    await db_client.post(f"/api/v1/notifications/{notification_id}/read", headers=headers)

    unread = (
        await db_client.get("/api/v1/notifications", params={"is_read": "false"}, headers=headers)
    ).json()
    assert notification_id not in [n["id"] for n in unread["items"]]


async def test_read_all_clears_unread(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await _seed_goal_achieved(db_client, headers)

    await db_client.post("/api/v1/notifications/read-all", headers=headers)

    unread = (
        await db_client.get("/api/v1/notifications", params={"is_read": "false"}, headers=headers)
    ).json()
    assert unread["total"] == 0


async def test_cannot_mark_another_users_notification_read(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    await _seed_goal_achieved(db_client, owner)
    notification_id = (await db_client.get("/api/v1/notifications", headers=owner)).json()["items"][
        0
    ]["id"]
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(
        f"/api/v1/notifications/{notification_id}/read", headers=intruder
    )

    assert response.status_code == 404


async def test_disabled_preference_suppresses_in_app_notification(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    await db_client.patch(
        "/api/v1/notifications/preferences",
        json=[{"type": "GOAL_ACHIEVED", "channel": "IN_APP", "is_enabled": False}],
        headers=headers,
    )

    await _seed_goal_achieved(db_client, headers)

    response = await db_client.get("/api/v1/notifications", headers=headers)
    assert "GOAL_ACHIEVED" not in [n["type"] for n in response.json()["items"]]


async def test_preferences_round_trip(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await db_client.patch(
        "/api/v1/notifications/preferences",
        json=[{"type": "BUDGET_EXCEEDED", "channel": "EMAIL", "is_enabled": False}],
        headers=headers,
    )

    prefs = (await db_client.get("/api/v1/notifications/preferences", headers=headers)).json()

    assert {"type": "BUDGET_EXCEEDED", "channel": "EMAIL", "is_enabled": False} in prefs
