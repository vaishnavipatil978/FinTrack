# FinTrack

A personal finance management API: multi-account ledgers, transactions,
transfers, category budgets, savings goals, recurring transactions, CSV
import, reporting, and admin tooling — built with FastAPI, PostgreSQL,
and Redis as a modular monolith.

> **Status**: Feature-complete and verified against a real PostgreSQL +
> Redis + Celery stack, including admin tooling, a clean dependency
> vulnerability scan (`pip-audit`), and a real Locust load test. 296
> automated tests pass. **Not deployed anywhere** — there is no
> provisioned cloud environment and the CI workflow has never run on a
> hosted runner. See [`docs/production-readiness.md`](docs/production-readiness.md)
> for the full, item-by-item status.

## 1. What this project does

FinTrack is the backend for a personal finance app. A user registers,
creates one or more accounts (bank, cash, credit card, savings,
investment, wallet), and then:

- Records income, expense, and transfer transactions, with every
  balance update happening atomically.
- Sets a monthly budget per category and sees live utilization
  (spent / limit) as transactions land.
- Sets savings goals with a target amount and date, and gets back
  progress percentage and the contribution still required to hit the
  target on time.
- Defines recurring transactions (e.g. rent on the 1st) that a
  background worker turns into real transactions on schedule, exactly
  once per occurrence — no duplicates even if the job is retried or
  crashes mid-run.
- Imports transaction history from a CSV file, with row-level
  validation, a preview/confirm step, and duplicate detection.
- Pulls monthly summaries, category breakdowns, account balances, and
  a combined budgets/goals snapshot.
- Gets in-app notifications when a budget is exceeded, a goal is
  achieved, or a recurring transaction posts.

Administrators (a separate `role` on the user, not a separate app) can
list/search users and lock or unlock an account, with every admin
action recorded in an audit trail.

Everything an authenticated user does to their own money is isolated
from everything every other user does — enforced at the database query
level, not just checked in a router.

## 2. Quick start

Requires Python 3.12+ and Docker.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # edit values as needed, especially FINTRACK_JWT_SECRET_KEY

docker compose up --build          # Postgres, Redis, API, Celery worker, Celery beat
docker compose run --rm api alembic upgrade head
```

Default host ports (deliberately non-standard, to avoid clashing with
other local services): API `8010`, PostgreSQL `55432`, Redis `6379`.
Containers reach each other on their normal ports (`db:5432`, etc.) —
only the host-side mapping is shifted. Adjust `docker-compose.yml` if
you'd rather use the conventional ports.

- Liveness: `GET http://localhost:8010/health`
- Readiness (checks the DB): `GET http://localhost:8010/ready`
- Interactive API docs: `http://localhost:8010/docs`
- Metrics (Prometheus format): `GET http://localhost:8010/metrics`

```bash
curl -X POST localhost:8010/api/v1/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery-staple","full_name":"Ada Lovelace"}'

curl -X POST localhost:8010/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"ada@example.com","password":"correct-horse-battery-staple"}'
# -> {"access_token": "...", "refresh_token": "...", "token_type": "bearer", "expires_in": 900}

curl localhost:8010/api/v1/users/me -H "Authorization: Bearer <access_token>"
```

To run the API without Docker (needs a reachable PostgreSQL matching
`FINTRACK_DATABASE_URL`):

```bash
uvicorn app.main:create_app --factory --reload
```

## 3. Architecture

Layered modular monolith — one deployable, four internal layers, each
only allowed to call the layer directly below it:

```
Router (app/api)        HTTP only: parse request, call one service method, shape response
   │
Service (app/services)  Business rules, transaction boundaries, orchestration
   │
Repository (app/repositories)  Query construction, nothing else
   │
Model (app/models)      SQLAlchemy ORM tables
```

```
Client → FastAPI (app/main.py)
              ├── PostgreSQL          (source of truth — every table)
              ├── Redis               (cache / rate limit / idempotency / Celery broker)
              └── Celery worker+beat  (recurring-transaction posting, async CSV import)
```

Why this shape, not microservices: a single user's request (e.g.
"create a transfer") touches accounts, transactions, budgets, and
notifications in one atomic unit of work. Splitting those into
separate services would turn one DB transaction into a distributed one
for no benefit at this scale. Full rationale and diagrams:
[`docs/architecture/system-architecture.md`](docs/architecture/system-architecture.md).

A few design decisions worth knowing before reading the code:

- **Money is always `Decimal`/`NUMERIC(18,2)`, never `float`.** A float
  balance is a silent-corruption bug waiting to happen; see
  `app/utils/money.py`.
- **Ownership is enforced in the repository's `WHERE` clause**, not
  just checked in the service. Every `get_owned_*` query filters by
  `user_id` directly, so there's no code path that *could* return
  another user's row even by accident. Cross-user access returns `404`
  (not `403`) everywhere, so a user can't even tell whether a resource
  ID belongs to someone else.
- **Transfers use `SELECT ... FOR UPDATE`** on both accounts before
  touching either balance, so concurrent transfers against the same
  account serialize instead of losing an update. Verified with a real
  10-way-concurrent test, not just a forced-delay unit test.
- **Recurring-transaction idempotency is a database constraint**, not
  an application-level check-then-insert: a unique constraint on
  `(recurring_rule_id, scheduled_date)` makes "process this occurrence
  twice" fail at the DB, not just "usually not happen."
- **Math that depends on "today" (goal progress, recurring due-dates)
  never calls the system clock.** `app/services/goal_math.py` and
  `app/services/recurring_math.py` take `today` as an explicit
  parameter, which is what makes their tests exact and reproducible
  instead of "probably right, ran when I wrote it."
- **Redis-backed features (cache, rate limit, idempotency keys) fail
  open.** If Redis is unreachable, requests still succeed — correctness
  never depends on Redis being up; it's purely an optimization/defense
  layer.

## 4. Code layout

```
app/
├── main.py              # app factory: middleware + router registration
├── core/                # config (pydantic-settings), structlog setup, JWT/password
│                         # hashing, centralized exception→HTTP mapping, Redis client,
│                         # cache, rate limiter, idempotency, Prometheus metrics
├── middleware/           # request-id injection + JSON request logging, security headers
├── db/                    # async SQLAlchemy engine/session factory
├── models/                 # SQLAlchemy ORM tables (users, accounts, transactions,
│                           # transfers, categories, budgets, goals + contributions,
│                           # recurring rules + occurrences, CSV import batches,
│                           # notifications, audit log, refresh/reset tokens)
├── schemas/                 # Pydantic v2 request/response models — one module per resource
├── api/v1/                   # routers: one module per resource, HTTP concern only
├── services/                   # business logic + transaction boundaries, one per resource;
│                               # goal_math.py / recurring_math.py are pure functions
├── repositories/                 # query construction, one module per aggregate,
│                                 # ownership-scoped at the query level
└── workers/                       # celery_app.py (broker/config) + tasks.py (recurring
                                    # posting, async CSV processing)

tests/
├── unit/        # pure logic, no I/O: security, config, money, goal/recurring math,
│                # audit-log metadata allowlist
├── integration/ # against a real PostgreSQL: migrations, transfer atomicity/concurrency,
│                # recurring idempotency (incl. against the real running Celery worker),
│                # Redis-backed features
└── api/         # full HTTP behavior via httpx, one module per resource, plus a
                 # cross-cutting security matrix (every protected route × unauthenticated/
                 # malformed-token/cross-user-access)

alembic/        # migrations — one source of truth for schema, no manual DDL anywhere
docs/           # requirements, architecture, API/DB design, and the review docs below
scripts/        # locustfile.py (load test)
```

296 tests total, run against a real Postgres/Redis/Celery stack, not
mocks — `pytest` by itself runs what doesn't need external services;
see [§7](#7-running-tests) for the full command.

## 5. Core functionality, by resource

| Resource | What it does | Key internal detail |
|---|---|---|
| **Auth** (`/auth`) | Register, login, refresh, logout, forgot/reset password | Opaque refresh tokens, hashed at rest, rotated on every use; reusing an already-rotated token revokes its entire token family (reuse-detection, not just rotation). Account lockout after repeated failed logins. |
| **Users** (`/users`) | Read/update own profile | — |
| **Accounts** (`/accounts`) | CRUD for ledgers (bank/cash/credit-card/savings/investment/wallet) | Credit-card accounts alone are allowed a negative balance; everything else is a business-rule violation, not a UI-only guard. |
| **Categories** (`/categories`) | System-seeded + user-defined spending categories | System categories are seeded by a data-only Alembic migration, not app-startup code. |
| **Transactions** (`/transactions`) | Income/expense entries | Supports an `Idempotency-Key` header so a retried POST can't double-post. |
| **Transfers** (`/transfers`) | Move money between two of the user's own accounts | Atomic: both legs succeed or neither does, enforced with row-level locks, not just a try/except. |
| **Budgets** (`/budgets`) | Per-category monthly spending limits | Utilization is computed from actual transactions at read time, not a maintained counter that can drift. |
| **Goals** (`/goals`) | Savings targets with progress tracking | Progress/required-contribution math is a pure, clock-free function — see §3. |
| **Recurring transactions** (`/recurring-transactions`) | Rules that generate transactions on a schedule | Posted by a daily Celery Beat job; idempotent by a DB constraint, not application logic. |
| **CSV import** (`/csv-imports`) | Bulk transaction upload | Structural + per-row validation, duplicate detection, explicit preview→confirm (nothing is written on upload alone); large files are processed asynchronously by the worker. |
| **Reports** (`/reports`) | Monthly summary, category breakdown, balances, budgets/goals snapshot | Monthly summary and balances are cached in Redis per user, invalidated on every ledger write (including worker-originated ones). |
| **Notifications** (`/notifications`) | In-app alerts: budget exceeded, goal achieved, recurring posted | Delivery is behind a `DeliveryChannel` protocol; only an in-app/log channel exists today (see §8). |
| **Audit log** (`/audit`) | Read your own history of sensitive actions | Metadata is allowlisted before write — a password or token passed in by mistake is dropped, not stored. |
| **Admin** (`/admin`) | List/search users, lock/unlock, cross-user audit view | Gated by `role == ADMIN`; deliberately returns no financial data, password hash, or token for any user — see §6. |

Full request/response contracts: [`docs/api-design.md`](docs/api-design.md),
or the live Swagger UI at `/docs`.

## 6. Cross-cutting internals

**Authentication & sessions** — JWT access tokens (15 min default,
minimal claims) + opaque, rotating refresh tokens with reuse detection.
`FINTRACK_JWT_SECRET_KEY` is required and must be ≥32 chars in
production (enforced at startup, not just documented); generate one
with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Full design: [`docs/architecture/security-architecture.md`](docs/architecture/security-architecture.md) §1.

**Authorization** — every resource is scoped to its owner inside the
repository's query, and cross-user access always returns `404`. Swept
end-to-end by `tests/api/test_security_matrix.py`.

**Admin** — `/admin/*` is gated by a `require_admin` dependency
checking `role == ADMIN` on the current user. It can list/search/
paginate users and lock or unlock an account (idempotent either way; an
admin can't lock themselves out). Locking a user immediately revokes
every refresh token they currently hold — a lock takes effect on their
next request, not just their next login. Every admin action is
audit-logged. No admin endpoint exposes another user's transactions,
balances, password hash, or active token.

**Redis-backed features** — rate limiting (fixed window per client IP
on login/register/refresh/password-reset), report caching (per-user
namespaced, invalidated on every ledger write), and idempotency keys
(`Idempotency-Key` header on `POST /transactions`, `POST /transfers`,
and CSV confirm — a concurrent duplicate gets `409
IDEMPOTENCY_IN_PROGRESS`, a sequential replay returns the original
response). All three fail open if Redis is down.

**Background jobs** — Celery worker + beat, started by `docker compose
up` alongside the API (same image, different `command:`). One
scheduled task today: `process_due_recurring_rules_task`, fired daily
at 00:15 UTC, safe to re-run or trigger manually:

```bash
docker compose exec worker celery -A app.workers.celery_app call \
  app.workers.tasks.process_due_recurring_rules_task
```

**Observability** — structured JSON logs (`structlog`) with a
request-id propagated through every log line in a request; Prometheus
metrics at `/metrics` (request count/latency by route template —not raw
path, to avoid cardinality blowup—, cache hit/miss, rate-limit
rejections, background job duration/failures); `/health` (liveness, no
dependency checks) and `/ready` (checks the DB) for orchestrator
probes.

**Database & migrations** — schema is entirely Alembic-managed; see
[`docs/database-design.md`](docs/database-design.md) and
[`app/models/`](app/models/). `alembic/env.py` reads the DB URL from
the same `Settings` object the app uses, so there's one source of
truth, not a second copy in `alembic.ini`.

```bash
alembic upgrade head        # apply all migrations
alembic downgrade base      # roll back to empty
alembic revision --autogenerate -m "add X"
```

Autogenerated migrations are always hand-reviewed — autogenerate
doesn't reliably capture `CHECK` constraints, partial indexes, or
circular foreign keys (this schema has one: `transactions` and
`recurring_occurrences` reference each other, requiring `use_alter`
and a hand-added deferred `op.create_foreign_key()` pair). One
migration is data-only — it seeds the system default categories via
`op.bulk_insert`, with the `type` column declared as the real
`category_type` enum, not a plain string (asyncpg's binding fails
otherwise even though the value looks like valid text).

## 7. Running tests

```bash
pytest                 # unit tests + platform/health API tests (no external services)
```

Tests that need a real PostgreSQL (most API tests, all of
`tests/integration/`) are skipped unless `FINTRACK_TEST_DATABASE_URL`
is set:

```bash
FINTRACK_TEST_DATABASE_URL=postgresql+asyncpg://fintrack:change-me@localhost:55432/fintrack pytest
```

DB-backed tests run against the real schema but stay isolated from
each other: each test gets one connection/transaction rolled back
afterward, using SQLAlchemy's `join_transaction_mode="create_savepoint"`
so a service's own internal `commit()` releases a savepoint instead of
ending the outer transaction — see the `db_session` fixture in
`tests/conftest.py`. `test_transfer_atomicity.py` and
`test_transfer_concurrency.py` deliberately break that pattern (they
need real, separately committed transactions to prove what they're
proving) and clean up their own rows afterward.

```bash
ruff check .
black --check .
mypy app
pip-audit                    # dependency vulnerability scan — also runs in CI
pre-commit install           # run all of the above automatically on commit
```

```bash
locust -f scripts/locustfile.py --host http://localhost:8010 \
    --headless -u 20 -r 5 -t 45s --csv scripts/locust_results
```

Load test against the running `docker compose` stack — see
[`docs/performance-review.md`](docs/performance-review.md) §7 for the
last recorded run and findings.

## 8. Known limitations & next improvements

Honestly tracked, not hidden — see
[`docs/production-readiness.md`](docs/production-readiness.md) for the
full item-by-item review this list is drawn from.

**Not yet deployed anywhere.** No cloud account or hosted CI runner is
reachable from this environment, so `.github/workflows/ci.yml` has
been validated by running every one of its steps locally, but never on
an actual GitHub Actions runner, and `docs/deployment.md` documents an
AWS target that has never been provisioned. This is the single largest
gap between "done" and "in production."

**Report cache benefit is unproven at demo-scale data.** Measured
median latency was within noise (12.1ms cached vs. 13.1ms uncached)
at this session's small transaction volume. Needs re-measuring against
a few thousand transactions per user before trusting the cache is
earning its complexity — see `docs/performance-review.md` §6.

**One load-test finding not yet investigated.** `POST /accounts`
showed a ~1s median under a 20-user burst, markedly slower than the
structurally similar `POST /transactions` (~68ms). Only 8 samples were
collected, so it isn't conclusive — flagged for profiling, not fixed —
see `docs/performance-review.md` §7.

**Email is a log-only stub.** `/auth/forgot-password` logs the reset
token as a structured log line instead of emailing it, and in-app
notifications have no real email delivery behind them. The
`DeliveryChannel` protocol (`app/services/notification_service.py`) is
already designed to take a real provider without touching call sites —
plugging one in is the next step, not a rewrite.

**Deliberately out of scope for this version** — not oversights, see
[`docs/01-product-requirements.md`](docs/01-product-requirements.md) §6:
multi-currency FX conversion, bank/account aggregation (Plaid-style),
joint/shared accounts, distributed tracing, read replicas.

## 9. Technology stack

| Concern | Choice |
|---|---|
| API framework | FastAPI (async), Pydantic v2 |
| Database | PostgreSQL 16, SQLAlchemy 2.x (async), Alembic |
| Cache / queue broker | Redis |
| Background jobs | Celery (worker + beat) |
| Auth | JWT access tokens + opaque rotating refresh tokens |
| Logging | structlog (JSON) |
| Testing | pytest, pytest-asyncio, httpx |
| Lint / format / types | ruff, black, mypy (strict) |
| Dependency scanning | pip-audit |
| Load testing | Locust |
| Containerization | Docker, Docker Compose |
| CI | GitHub Actions |
