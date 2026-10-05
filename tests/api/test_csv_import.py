from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import auth_headers, create_account, create_transaction, get_category_id

HEADER = "date,description,amount,type,category,account\n"


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    content: bytes,
    filename: str = "transactions.csv",
) -> Response:
    return await client.post(
        "/api/v1/transactions/import",
        files={"file": (filename, content, "text/csv")},
        headers=headers,
    )


def _csv(*rows: str) -> bytes:
    return (HEADER + "\n".join(rows) + "\n").encode("utf-8")


# --- Structural validation (UC-10 alt-flow 2a) ----------------------------


async def test_rejects_non_csv_extension(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _upload(db_client, headers, _csv(), filename="data.txt")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_FORMAT"


async def test_rejects_missing_required_columns(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _upload(db_client, headers, b"date,amount\n2026-09-01,100\n")

    assert response.status_code == 400
    assert "missing required columns" in response.json()["error"]["message"]


async def test_rejects_non_utf8_content(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _upload(db_client, headers, HEADER.encode() + b"\xff\xfe\x00bad\n")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_FORMAT"


async def test_rejects_file_with_no_data_rows(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)

    response = await _upload(db_client, headers, HEADER.encode())

    assert response.status_code == 400
    assert "no data rows" in response.json()["error"]["message"]


# --- Preview (validation, nothing committed) --------------------------------


async def test_preview_reports_invalid_rows_with_per_row_errors(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers, name="Bank")

    response = await _upload(
        db_client,
        headers,
        _csv(
            "2026-09-01,Good row,100.00,EXPENSE,Food,Bank",
            "not-a-date,Bad date,100.00,EXPENSE,Food,Bank",
            "2026-09-02,Bad amount,abc,EXPENSE,Food,Bank",
            "2026-09-03,Unknown account,50.00,EXPENSE,Food,Nowhere",
        ),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total_rows"] == 4
    assert body["valid_rows"] == 1
    invalid_rows = {issue["row_number"]: issue["errors"] for issue in body["invalid_rows"]}
    assert set(invalid_rows) == {2, 3, 4}
    assert any("date" in e for e in invalid_rows[2])
    assert any("amount" in e for e in invalid_rows[3])
    assert any("Unknown account" in e for e in invalid_rows[4])


async def test_preview_commits_nothing(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, name="Bank", opening_balance="500.00")

    await _upload(
        db_client,
        headers,
        _csv("2026-09-01,Groceries,100.00,EXPENSE,Food,Bank"),
    )

    balance = (
        await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    ).json()
    assert balance["balance"] == "500.00"
    txns = (await db_client.get("/api/v1/transactions", headers=headers)).json()
    assert txns["total"] == 0


async def test_category_type_mismatch_is_an_invalid_row(db_client: AsyncClient) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers, name="Bank")

    response = await _upload(
        db_client,
        headers,
        _csv("2026-09-01,Paycheck,500.00,INCOME,Food,Bank"),
    )

    body = response.json()
    assert body["valid_rows"] == 0
    assert any("does not match" in e for e in body["invalid_rows"][0]["errors"])


# --- Duplicate detection (FR-CSV-05) ----------------------------------------


async def test_row_matching_an_existing_transaction_is_flagged_as_duplicate(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, name="Bank")
    food_id = await get_category_id(db_client, headers, name="Food")
    existing = await create_transaction(
        db_client,
        headers,
        account_id=account["id"],
        category_id=food_id,
        amount="100.00",
        transaction_date="2026-09-01",
        description="Groceries",
    )

    response = await _upload(
        db_client,
        headers,
        _csv("2026-09-01,Groceries,100.00,EXPENSE,Food,Bank"),
    )

    body = response.json()
    assert body["valid_rows"] == 0
    assert len(body["potential_duplicates"]) == 1
    assert body["potential_duplicates"][0]["existing_transaction_id"] == existing["id"]


# --- Confirm (UC-10 main flow) ----------------------------------------------


async def test_preview_then_confirm_imports_valid_rows_and_updates_balance(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, name="Bank", opening_balance="1000.00")
    preview = (
        await _upload(
            db_client,
            headers,
            _csv(
                "2026-09-01,Groceries,200.00,EXPENSE,Food,Bank",
                "2026-09-02,Paycheck,500.00,INCOME,Salary,Bank",
            ),
        )
    ).json()

    response = await db_client.post(
        f"/api/v1/transactions/import/{preview['batch_id']}/confirm",
        json={},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "COMPLETED"
    assert report["imported_rows"] == 2
    assert report["skipped_rows"] == 0

    balance = (
        await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    ).json()
    assert balance["balance"] == "1300.00"  # 1000 - 200 + 500


async def test_confirm_with_row_selection_skips_unselected_valid_rows(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers, name="Bank")
    preview = (
        await _upload(
            db_client,
            headers,
            _csv(
                "2026-09-01,First,10.00,EXPENSE,Food,Bank",
                "2026-09-02,Second,20.00,EXPENSE,Food,Bank",
            ),
        )
    ).json()
    detail = (
        await db_client.get(f"/api/v1/transactions/import/{preview['batch_id']}", headers=headers)
    ).json()
    assert detail["total_rows"] == 2

    # Confirm with an empty selection: nothing imported, both valid rows skipped.
    response = await db_client.post(
        f"/api/v1/transactions/import/{preview['batch_id']}/confirm",
        json={"row_ids_to_import": []},
        headers=headers,
    )

    assert response.json()["imported_rows"] == 0
    assert response.json()["skipped_rows"] == 2


async def test_confirming_twice_is_rejected_and_does_not_double_import(
    db_client: AsyncClient,
) -> None:
    headers = await auth_headers(db_client)
    account = await create_account(db_client, headers, name="Bank", opening_balance="1000.00")
    preview = (
        await _upload(db_client, headers, _csv("2026-09-01,Groceries,100.00,EXPENSE,Food,Bank"))
    ).json()
    url = f"/api/v1/transactions/import/{preview['batch_id']}/confirm"

    first = await db_client.post(url, json={}, headers=headers)
    second = await db_client.post(url, json={}, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "BATCH_ALREADY_CONFIRMED"
    balance = (
        await db_client.get(f"/api/v1/accounts/{account['id']}/balance", headers=headers)
    ).json()
    assert balance["balance"] == "900.00"


async def test_expired_preview_returns_410(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    headers = await auth_headers(db_client)
    await create_account(db_client, headers, name="Bank")
    preview = (
        await _upload(db_client, headers, _csv("2026-09-01,Groceries,100.00,EXPENSE,Food,Bank"))
    ).json()
    await db_session.execute(
        text("UPDATE csv_import_batches SET created_at = now() - interval '2 days' WHERE id = :id"),
        {"id": preview["batch_id"]},
    )

    response = await db_client.post(
        f"/api/v1/transactions/import/{preview['batch_id']}/confirm", json={}, headers=headers
    )

    assert response.status_code == 410
    assert response.json()["error"]["code"] == "BATCH_EXPIRED"


# --- Cross-user isolation -------------------------------------------------


async def test_cannot_confirm_another_users_batch(db_client: AsyncClient) -> None:
    owner = await auth_headers(db_client, email="owner@example.com")
    await create_account(db_client, owner, name="Bank")
    preview = (
        await _upload(db_client, owner, _csv("2026-09-01,Groceries,100.00,EXPENSE,Food,Bank"))
    ).json()
    intruder = await auth_headers(db_client, email="intruder@example.com")

    response = await db_client.post(
        f"/api/v1/transactions/import/{preview['batch_id']}/confirm", json={}, headers=intruder
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BATCH_NOT_FOUND"
