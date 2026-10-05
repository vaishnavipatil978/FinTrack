# FinTrack

A production-grade personal finance management API: accounts, transactions,
transfers, budgets, goals, recurring transactions, CSV import, and
reporting — built with FastAPI, PostgreSQL, and Redis as a modular
monolith.

> **Status**: Stages 1-16 complete, plus a production-readiness pass:
> admin tooling (`FR-ADMIN-01/02/03`), a dependency vulnerability scan
> (`pip-audit`, clean), and a real Locust load test against the local
> stack have all been added and verified. The application, tests,
> background processing, observability, admin endpoints, and docs are
> done and verified. **Not deployed anywhere** - no cloud account or
> GitHub remote is reachable from this environment, so the CI workflow
> has never run on a hosted runner. See
> [`docs/production-readiness.md`](docs/production-readiness.md) for
> the full, item-by-item status against the Definition of Done. See
> [`docs/06-development-roadmap.md`](docs/06-development-roadmap.md) for
> what's built vs. planned. This README is updated at the end of every
> stage.

## Project Overview

FinTrack lets a user track money across multiple accounts, record income/
expense/transfer activity with atomic ledger updates, set category
budgets and savings goals, automate recurring transactions, import
transaction history from CSV, and generate financial reports — all
behind a secure, observable, well-tested REST API. Full requirements and
design are in [`docs/`](docs/); see especially
[`docs/01-product-requirements.md`](docs/01-product-requirements.md) for
scope and [`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md)
for the system design.

No AI features. No microservices. A modular monolith, built in staged,
reviewed increments — see the engineering rules in
[`docs/06-development-roadmap.md`](docs/06-development-roadmap.md).

## Features (Planned Scope)

- JWT auth with refresh-token rotation and reuse detection
- Multi-account ledger (bank, cash, credit card, savings, investment, wallet)
- Income / expense / transfer transactions with atomic balance updates
- Category budgets with live utilization tracking
- Financial goals with progress and required-contribution calculations
- Idempotent recurring transactions via a background worker
- CSV transaction import with preview, validation, and duplicate detection
- Monthly financial reports and category breakdowns
- In-app + pluggable email notifications
- Append-only audit logging of sensitive actions
- Redis-backed caching, rate limiting, and idempotency keys
- Structured JSON logging, Prometheus metrics, liveness/readiness probes

## Architecture

Layered modular monolith: **API (routers) → Service → Repository →
PostgreSQL**, with Redis and a Celery worker as supporting infrastructure.
Full diagrams and rationale: [`docs/architecture/`](docs/architecture/).

```
Client → Load Balancer → FastAPI (N replicas) → PostgreSQL
                                ├── Redis (cache / rate limit / idempotency / broker)
                                └── Celery Worker (recurring txns, large CSV import, notifications)
```

## Technology Stack

| Concern | Choice |
|---|---|
| API framework | FastAPI (async), Pydantic v2 |
| Database | PostgreSQL 16, SQLAlchemy 2.x (async), Alembic |
| Cache / queue broker | Redis |
| Background jobs | Celery |
| Auth | JWT (access) + opaque rotating refresh tokens |
| Logging | structlog (JSON) |
| Testing | pytest, pytest-asyncio, httpx |
| Lint / format / types | ruff, black, mypy (strict) |
| Containerization | Docker, Docker Compose |
| CI | GitHub Actions |

## Project Structure

```
fintrack/
├── app/
│   ├── main.py          # app factory, middleware/router registration
│   ├── core/             # config, logging, centralized exceptions, request context
│   ├── api/               # routers (HTTP concern only)
│   ├── middleware/        # request-id/logging, security headers
│   ├── db/                # SQLAlchemy engine/session setup
│   ├── models/             # SQLAlchemy ORM models - 18 tables
│   ├── utils/               # money/decimal/period helpers
│   ├── schemas/               # Pydantic request/response models
│   ├── services/                # business logic, incl. goal_math.py and
│   │                            # recurring_math.py - pure, deterministic
│   │                            # calculations (no I/O, no clock access)
│   ├── repositories/              # data access, one module per aggregate
│   └── workers/                     # celery_app.py + tasks.py (Stage 7)
├── tests/
│   ├── unit/           # business logic, no I/O (incl. security.py, config)
│   ├── integration/     # real PostgreSQL - migrations, connectivity, transfer
│   │                    # atomicity/concurrency, and recurring idempotency
│   ├── helpers.py       # shared register/login/account test helpers
│   └── api/               # HTTP behavior via httpx (most flows use a real,
│                          # per-test-transaction PostgreSQL - see conftest.py)
├── alembic/             # env.py + versions/ - migrations (Stage 2+)
├── docs/                # requirements, architecture, API/DB design
├── scripts/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── .env.example
```

## Local Setup

Requires Python 3.12+ and Docker.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # edit values as needed
```

## Environment Variables

See [`.env.example`](.env.example) for the full list. Key variables:

| Variable | Purpose |
|---|---|
| `FINTRACK_ENVIRONMENT` | `development` \| `testing` \| `production` |
| `FINTRACK_DATABASE_URL` | Async SQLAlchemy PostgreSQL URL |
| `FINTRACK_CORS_ORIGINS` | Comma-separated allowed origins (no `*` in production) |
| `FINTRACK_LOG_LEVEL` | Log verbosity |

Settings are loaded via `pydantic-settings` and fail fast at startup if a
required variable is missing.

## Database Setup & Migrations

Schema is fully managed by Alembic — see
[`docs/database-design.md`](docs/database-design.md) for the design and
[`app/models/`](app/models/) for the SQLAlchemy models. `alembic/env.py`
reads `FINTRACK_DATABASE_URL` from the same `Settings` the app uses, so
there's one source of truth for the DB URL, not a second copy in
`alembic.ini`.

```bash
alembic upgrade head        # apply all migrations
alembic downgrade base      # roll back to empty (used to verify migrations)
alembic revision --autogenerate -m "add X"   # generate a new migration after model changes
```

Autogenerated migrations are always hand-reviewed before commit —
autogenerate does not reliably capture `CHECK` constraints, partial
indexes, or circular foreign keys (this project has one: `transactions`
and `recurring_occurrences` reference each other, requiring `use_alter`
and a hand-added deferred `op.create_foreign_key()` pair — see the
initial migration for the pattern and `docs/database-design.md` §6 for
why the cycle exists).

One migration (`308509395ce3_seed_system_categories`) is data-only — it
seeds the system default categories (FR-CAT-01) rather than changing the
schema. Its `upgrade()` uses `op.bulk_insert`; the `type` column must be
declared as the real `category_type` enum there (not a plain string), or
asyncpg's parameter binding fails with a type-mismatch error at insert
time even though the value looks like valid enum text.

Current migration chain: initial schema → password reset tokens →
`users.locked_until` (auto-expiring lockout, added during Stage 3) → seed
system categories (added during Stage 5, since transactions require a
category).

## Running the App Locally (without Docker)

Requires a reachable PostgreSQL instance matching `FINTRACK_DATABASE_URL`.

```bash
uvicorn app.main:create_app --factory --reload
```

- Liveness: `GET http://localhost:8000/health`
- Readiness: `GET http://localhost:8000/ready`
- OpenAPI docs: `http://localhost:8000/docs`

## Docker Setup

```bash
docker compose up --build
docker compose run --rm api alembic upgrade head   # apply migrations
```

Brings up PostgreSQL, Redis, and the API. Postgres and Redis have
healthchecks; the API waits for both before starting. Migrations are run
explicitly, not automatically on container boot — auto-migrating on every
replica's startup risks multiple instances racing the same migration in a
multi-replica deployment.

Default host port mappings (only affect access *from the host* — containers
always reach each other over the compose network on the service's normal
port, e.g. `db:5432`): API on `8010`, PostgreSQL on `55432`, Redis on
`6379`. The API and Postgres ports are deliberately non-default (`8000`/
`5432`) to avoid clashing with other services commonly already running on a
dev machine; adjust the `ports:` mappings in
[`docker-compose.yml`](docker-compose.yml) if you'd prefer the conventional
ports and they're free on yours. With the defaults: `http://localhost:8010/health`,
`http://localhost:8010/ready`, `http://localhost:8010/docs`.

## Redis, Caching, Rate Limiting & Idempotency

Redis backs four things, each failing open if Redis is down (requests still
succeed, the failure is logged):

- **Rate limiting** on login, register, refresh, forgot/reset-password (fixed
  window per client IP; `FINTRACK_RATE_LIMIT_AUTH_PER_MINUTE`, default 10).
- **Report caching** for the monthly summary and balances, namespaced per user.
  Every ledger write invalidates the user's cached reports, including writes
  made by the background worker.
- **Idempotency keys** on `POST /transactions`, `POST /transfers`, and CSV
  confirm. A repeated `Idempotency-Key` replays the stored response instead of
  posting twice. A concurrent duplicate gets `409 IDEMPOTENCY_IN_PROGRESS`.

## Background Jobs

`docker compose up` also starts `worker` (Celery worker) and `beat`
(Celery beat scheduler) — see
[`docs/architecture/background-jobs.md`](docs/architecture/background-jobs.md).
Both reuse the `api` image (same `Dockerfile`, no separate build) and run
as the same non-root container user, which is why `beat` points its
schedule file at `/tmp/celerybeat-schedule` instead of the app directory
— the app directory isn't writable by that user, by design.

Currently one scheduled task: `process_due_recurring_rules_task`, which
`beat` fires daily at 00:15 UTC and which is idempotent by construction
(see Stage 7 notes below) — safe to re-run, retry, or trigger manually:

```bash
docker compose exec worker celery -A app.workers.celery_app call \
  app.workers.tasks.process_due_recurring_rules_task
docker compose logs worker --tail 20
```

## Running Tests

```bash
pytest                 # unit tests + platform/health API tests (no external services)
```

Tests that need a real PostgreSQL (DB-backed API tests — auth, users — and
the `tests/integration/` suite) are skipped unless
`FINTRACK_TEST_DATABASE_URL` is set:

```bash
FINTRACK_TEST_DATABASE_URL=postgresql+asyncpg://fintrack:change-me@localhost:55432/fintrack pytest
```

(Port `55432` matches the default `docker-compose.yml` mapping — see
Docker Setup above. Adjust if you changed it or are pointing at a
different PostgreSQL instance.)

DB-backed tests run against the real schema but stay isolated from each
other: each test gets one connection/transaction that's rolled back
afterwards, using SQLAlchemy's `join_transaction_mode="create_savepoint"`
so a service's own internal `commit()` calls don't end the outer
transaction early — see the `db_session` fixture in `tests/conftest.py`.

Two tests in `tests/integration/` deliberately break that pattern because
they need real, separately-committed transactions:
- `test_transfer_atomicity.py` forces a failure between a transfer's two
  legs and asserts both account balances are completely untouched
  (UC-07 alt-flow 4a).
- `test_transfer_concurrency.py` races ten genuinely concurrent transfers
  (separate connections) against the same source account and asserts the
  final balance reflects all ten debits — proving the row lock actually
  serializes them rather than losing an update (UC-07 alt-flow 4b). Each
  test cleans up its own rows afterward since nothing here gets rolled
  back automatically.

Goal progress/required-contribution math (`app/services/goal_math.py`)
never reads the system clock — `today` is always an explicit parameter.
`tests/unit/test_goal_math.py` exercises it with fixed dates and exact
expected `Decimal` outputs (including the achieved/overdue/exact-boundary
edge cases), independent of whenever the suite happens to run. API-level
goal tests then only need to confirm the service wires that function up
correctly, using a far-future/far-past target date to keep the
overdue/not-overdue branch deterministic without freezing time at the
HTTP layer.

`tests/integration/test_recurring_idempotency.py` proves UC-09's
idempotency guarantee directly against the service layer: double-invoking
`process_occurrence()` for the same `(rule, scheduled_date)` creates
exactly one transaction, and a simulated crash between the transaction
insert and its occurrence-row anchor (mocked to raise) leaves zero
orphaned rows — a retry afterward succeeds cleanly with no duplicate.
This was also verified against the real, running Celery worker container
(not just pytest): triggering the task twice in a row for the same due
rule produced `transactions_created=2` then `transactions_created=0`.

## Code Quality

```bash
ruff check .
black --check .
mypy app
pip-audit             # dependency vulnerability scan - also runs in CI
pre-commit install   # run all of the above automatically on commit
```

## Load Testing

```bash
locust -f scripts/locustfile.py --host http://localhost:8010 \
    --headless -u 20 -r 5 -t 45s --csv scripts/locust_results
```

Simulates realistic traffic against the running `docker compose` stack
(mostly reads — list transactions/accounts, pull reports — with
occasional transaction creation). See
[`docs/performance-review.md`](docs/performance-review.md) §7 for the
last recorded run's numbers and findings.

## Admin

Admin-only endpoints (`require_admin`, role `ADMIN`) under `/api/v1/admin`:
list/search/paginate users, lock/unlock a user (idempotent, self-lock
rejected, lock revokes every active refresh token immediately), and a
cross-user audit log view. Deliberately narrow — no admin endpoint
returns another user's financial data, password hash, or active token.
See [`docs/security-review.md`](docs/security-review.md) §2.

## Authentication

JWT access tokens (15 min default) + opaque, rotating refresh tokens with
reuse detection — see
[`docs/architecture/security-architecture.md`](docs/architecture/security-architecture.md)
§1 for the full design and `docs/architecture/data-flow.md` §6 for the
token lifecycle. Quick tour once the app is running:

```bash
curl -X POST localhost:8010/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery-staple","full_name":"Ada Lovelace"}'

curl -X POST localhost:8010/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery-staple"}'
# -> {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 900}

curl localhost:8010/api/v1/users/me -H "Authorization: Bearer <access_token>"
```

`FINTRACK_JWT_SECRET_KEY` is required (min 32 chars enforced in
production); generate one with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. There is
no email provider yet (lands in Stage 10), so `/auth/forgot-password`
logs the raw reset token as a structured log line in non-production
environments instead of emailing it — never in production, and never as
the final implementation.

## API Documentation

Full endpoint-by-endpoint contract: [`docs/api-design.md`](docs/api-design.md).
Interactive Swagger UI is served at `/docs` once the app is running.

## Deployment

Not yet built — see Stage 15 in
[`docs/06-development-roadmap.md`](docs/06-development-roadmap.md). AWS
deployment details will live in `docs/deployment.md` once that stage
starts.

## Future Improvements

Documented, deliberately out of scope for v1 — see
[`docs/01-product-requirements.md`](docs/01-product-requirements.md) §6
and the "explicitly out of scope" notes throughout `docs/architecture/`:
multi-currency FX conversion, bank aggregation (Plaid-style), joint/shared
accounts, distributed tracing, read replicas.
