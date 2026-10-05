from httpx import AsyncClient, Response

from tests.helpers import auth_headers, create_account

FAR_FUTURE = "2099-12-31"  # safely not-overdue for any plausible test-run date
FAR_PAST = "2020-01-01"  # safely overdue for any plausible test-run date


async def _create_goal(
    client: AsyncClient, headers: dict[str, str], **overrides: object
) -> Response:
    payload: dict[str, object] = {
        "name": "Emergency Fund",
        "target_amount": "300000.00",
        "currency": "INR",
        "target_date": FAR_FUTURE,
        **overrides,
    }
    return await client.post("/api/v1/goals", json=payload, headers=headers)


# --- Create ------------------------------------------------------------


async def test_create_goal(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _create_goal(db_client, headers, current_amount="125000.00")

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["progress_pct"] == "41.67"
    assert body["remaining_amount"] == "175000.00"
    assert body["is_achieved"] is False
    assert body["is_overdue"] is False
    assert body["status"] == "ACTIVE"


async def test_create_goal_already_met_is_immediately_achieved(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _create_goal(
        db_client, headers, target_amount="1000.00", current_amount="1000.00"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["is_achieved"] is True
    assert body["status"] == "ACHIEVED"
    assert body["required_monthly_contribution"] == "0.00"


async def test_create_goal_defaults_current_amount_to_zero(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _create_goal(db_client, headers)

    assert response.json()["current_amount"] == "0.00"


async def test_overdue_unachieved_goal_has_no_monthly_contribution(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _create_goal(db_client, headers, target_date=FAR_PAST, current_amount="100.00")

    body = response.json()
    assert body["is_overdue"] is True
    assert body["is_achieved"] is False
    assert body["required_monthly_contribution"] is None


async def test_create_goal_rejects_zero_target(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _create_goal(db_client, headers, target_amount="0.00")

    assert response.status_code == 422


# --- Contributions -----------------------------------------------------


async def test_contribution_increases_current_amount_and_progress(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers, target_amount="1000.00")).json()

    response = await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "400.00", "contributed_at": "2026-09-01"},
        headers=headers,
    )
    assert response.status_code == 201

    fetched = (await db_client.get(f"/api/v1/goals/{goal['id']}", headers=headers)).json()
    assert fetched["current_amount"] == "400.00"
    assert fetched["progress_pct"] == "40.00"


async def test_contribution_that_reaches_target_marks_goal_achieved(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers, target_amount="1000.00")).json()

    await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "1000.00", "contributed_at": "2026-09-01"},
        headers=headers,
    )

    fetched = (await db_client.get(f"/api/v1/goals/{goal['id']}", headers=headers)).json()
    assert fetched["status"] == "ACHIEVED"
    assert fetched["is_achieved"] is True


async def test_contribution_can_reference_an_owned_account(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()
    account = await create_account(db_client, headers)

    response = await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={
            "amount": "100.00",
            "contributed_at": "2026-09-01",
            "source_account_id": account["id"],
        },
        headers=headers,
    )

    assert response.status_code == 201
    assert response.json()["source_account_id"] == account["id"]


async def test_contribution_cannot_reference_another_users_account(
    db_client: AsyncClient,
) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    goal = (await _create_goal(db_client, owner)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")
    intruder_account = await create_account(db_client, intruder)

    response = await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={
            "amount": "100.00",
            "contributed_at": "2026-09-01",
            "source_account_id": intruder_account["id"],
        },
        headers=owner,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ACCOUNT_NOT_FOUND"


async def test_list_contributions(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()
    await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "100.00", "contributed_at": "2026-09-01"},
        headers=headers,
    )
    await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "200.00", "contributed_at": "2026-09-02"},
        headers=headers,
    )

    response = await db_client.get(f"/api/v1/goals/{goal['id']}/contributions", headers=headers)

    body = response.json()
    assert body["total"] == 2
    assert {c["amount"] for c in body["items"]} == {"100.00", "200.00"}


# --- Update / close ------------------------------------------------------


async def test_update_goal_name_and_target(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()

    response = await db_client.patch(
        f"/api/v1/goals/{goal['id']}",
        json={"name": "New Car Fund", "target_amount": "500000.00"},
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Car Fund"
    assert body["target_amount"] == "500000.00"


async def test_close_goal(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()

    response = await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=headers)
    assert response.status_code == 204

    fetched = (await db_client.get(f"/api/v1/goals/{goal['id']}", headers=headers)).json()
    assert fetched["status"] == "CLOSED"


async def test_closing_twice_is_idempotent(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()
    await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=headers)

    response = await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=headers)

    assert response.status_code == 204


async def test_cannot_update_a_closed_goal(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()
    await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=headers)

    response = await db_client.patch(
        f"/api/v1/goals/{goal['id']}", json={"name": "New Name"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "GOAL_CLOSED"


async def test_cannot_contribute_to_a_closed_goal(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    goal = (await _create_goal(db_client, headers)).json()
    await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=headers)

    response = await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "10.00", "contributed_at": "2026-09-01"},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "GOAL_CLOSED"


# --- List filtering / pagination -----------------------------------------


async def test_list_goals_filters_by_status(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    active = (await _create_goal(db_client, headers, name="Active Goal")).json()
    closed = (await _create_goal(db_client, headers, name="Closed Goal")).json()
    await db_client.post(f"/api/v1/goals/{closed['id']}/close", headers=headers)

    response = await db_client.get("/api/v1/goals", params={"status": "ACTIVE"}, headers=headers)

    ids = [g["id"] for g in response.json()["items"]]
    assert active["id"] in ids
    assert closed["id"] not in ids


# --- Cross-user isolation ---------------------------------------------------


async def test_cannot_view_another_users_goal(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    goal = (await _create_goal(db_client, owner)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.get(f"/api/v1/goals/{goal['id']}", headers=intruder)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "GOAL_NOT_FOUND"


async def test_cannot_contribute_to_another_users_goal(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    goal = (await _create_goal(db_client, owner)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(
        f"/api/v1/goals/{goal['id']}/contributions",
        json={"amount": "10.00", "contributed_at": "2026-09-01"},
        headers=intruder,
    )

    assert response.status_code == 404


async def test_cannot_close_another_users_goal(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    goal = (await _create_goal(db_client, owner)).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(f"/api/v1/goals/{goal['id']}/close", headers=intruder)

    assert response.status_code == 404
    still_active = (await db_client.get(f"/api/v1/goals/{goal['id']}", headers=owner)).json()
    assert still_active["status"] == "ACTIVE"
