"""Load test for FinTrack's core read/write paths (root prompt §33).

Run against the local docker-compose stack:

    locust -f scripts/locustfile.py --host http://localhost:8010 \
        --headless -u 20 -r 5 -t 60s --csv scripts/locust_results

Each simulated user registers once (on_start), then exercises the
day-to-day mix a real user would: mostly reads (list transactions,
accounts, reports) with occasional writes (create a transaction).
"""

import random
import uuid

from locust import HttpUser, between, task


class FinTrackUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        email = f"loadtest-{uuid.uuid4().hex}@example.com"
        password = (
            "correct-horse-battery-staple"  # noqa: S105 - load-test fixture, not a credential
        )
        self.client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "full_name": "Load Test User"},
        )
        login_response = self.client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        token = login_response.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {token}"}

        account_response = self.client.post(
            "/api/v1/accounts",
            json={
                "name": "Load Test Account",
                "type": "BANK",
                "currency": "INR",
                "opening_balance": "1000.00",
            },
            headers=self.headers,
        )
        self.account_id = account_response.json()["id"]

        categories_response = self.client.get("/api/v1/categories", headers=self.headers)
        self.category_id = categories_response.json()[0]["id"]

    @task(5)
    def list_transactions(self) -> None:
        self.client.get("/api/v1/transactions", headers=self.headers)

    @task(3)
    def list_accounts(self) -> None:
        self.client.get("/api/v1/accounts", headers=self.headers)

    @task(2)
    def monthly_summary_report(self) -> None:
        self.client.get(
            "/api/v1/reports/monthly-summary",
            params={"month": 9, "year": 2026},
            headers=self.headers,
        )

    @task(1)
    def create_transaction(self) -> None:
        self.client.post(
            "/api/v1/transactions",
            json={
                "account_id": self.account_id,
                "type": "EXPENSE",
                "amount": f"{random.uniform(5, 200):.2f}",  # noqa: S311 - load-test data, not security-sensitive
                "currency": "INR",
                "category_id": self.category_id,
                "transaction_date": "2026-09-15",
                "description": "Load test transaction",
            },
            headers=self.headers,
        )
