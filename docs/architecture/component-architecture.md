# FinTrack — Component Architecture

This document defines the internal code organization of the FastAPI
application: layers, module boundaries, and dependency rules. It is the
contract the Stage 1+ implementation must follow.

## 1. Layers

```
app/
├── main.py              # app factory, middleware/router registration
├── core/                # config, security primitives, logging, exceptions
├── api/                 # routers — HTTP concern only
│   └── v1/
│       ├── auth.py
│       ├── users.py
│       ├── accounts.py
│       ├── transactions.py
│       ├── transfers.py
│       ├── categories.py
│       ├── budgets.py
│       ├── goals.py
│       ├── recurring_transactions.py
│       ├── csv_import.py
│       ├── reports.py
│       ├── notifications.py
│       ├── audit.py
│       └── admin.py
├── schemas/             # Pydantic request/response models, one file per module
├── services/            # business logic, one file/class per module
├── repositories/        # SQLAlchemy query/write logic, one file per module
├── models/              # SQLAlchemy ORM models (matches database-design.md)
├── db/                  # engine/session setup, base class
├── workers/             # Celery app, tasks, beat schedule
├── middleware/           # request-id, logging, security headers
└── utils/               # currency/decimal helpers, pagination helpers
```

### Layer responsibilities

| Layer | Responsibility | Must NOT do |
|---|---|---|
| **api/** (routers) | Parse/validate HTTP input via Pydantic schemas, call exactly one service method, map the result/exception to an HTTP response. | Contain business logic, construct SQLAlchemy queries, or reference ORM models directly. |
| **schemas/** | Define request/response shapes, field-level validation (e.g., amount > 0, valid enum values). | Contain business rules that depend on database state (e.g., "category must belong to this user" is a service concern, not a schema concern). |
| **services/** | Implement business rules, ownership/authorization checks, orchestrate one or more repositories, own DB transaction boundaries for multi-step writes, raise domain exceptions. | Import FastAPI (`Request`, `Depends`) or construct HTTP responses — services are framework-agnostic and unit-testable without an HTTP layer. |
| **repositories/** | Translate service calls into SQLAlchemy queries/writes, scoped by `user_id` where applicable. | Contain business rules (e.g., a repository does not decide whether a budget already exists for a period — it just queries/writes what it's told; the service decides what that means). |
| **models/** | SQLAlchemy ORM table definitions matching `docs/database-design.md`. | Contain business logic methods beyond simple derived properties (e.g., a `Goal.progress_pct` computed property is acceptable; a `Goal.notify_if_achieved()` method that talks to the notification service is not — that belongs in the service layer). |
| **workers/** | Celery task definitions that call into the *same* service layer used by the API. | Duplicate business logic — a recurring transaction is created via `TransactionService`, not a parallel worker-only code path. |

Dependency direction is strictly top-down: `api → services → repositories
→ models`. A lower layer never imports from a higher layer. `schemas` are
imported by `api` (and by `services` only for input/output typing at
service boundaries where useful) but schemas never import services.

## 2. Dependency Injection

FastAPI's `Depends` is used for:

- `get_db_session()` — yields a scoped SQLAlchemy session per request,
  closed/rolled back automatically on exception.
- `get_current_user()` — decodes and validates the JWT from the
  `Authorization` header, loads the user, raises 401 if invalid/expired,
  raises 403 if the account is locked.
- `require_admin()` — wraps `get_current_user` and additionally checks
  `role == ADMIN`, for admin-only routers.
- `get_<module>_service()` — constructs a service instance with its
  required repository/session dependencies wired in.

This makes every service trivially substitutable in tests (e.g., a test
can override `get_current_user` to inject a fixed test user, or construct
a service directly with an in-memory/test-DB session without going
through FastAPI at all for pure unit tests).

## 3. Cross-Module Boundaries

Modules are allowed to depend on each other's **service layer** (never
directly on another module's repository or ORM models beyond what's
needed for a FK/join), so business rules stay in one place. Examples:

- `TransactionService` depends on `AccountService` to validate account
  ownership/state before writing a transaction — it does not re-implement
  "does this account belong to this user" itself.
- `BudgetService` depends on `TransactionService`'s query capability (or
  a shared `reporting` query helper) to compute spend-to-date; it does not
  duplicate the aggregation query.
- `TransferService` depends on `AccountService` for ownership/currency
  checks but performs the locked, atomic double-write itself (this is the
  one place where the operation is inherently cross-account and owns its
  own transaction boundary — see `data-flow.md`).
- `RecurringTransactionService` (invoked from the worker) depends on
  `TransactionService` to materialize the actual transaction, so a
  recurring-generated transaction is indistinguishable in business logic
  from a manually created one, except for its `recurring_occurrence_id`
  link.
- `NotificationService` is depended on by `BudgetService`,
  `GoalService`, `RecurringTransactionService`, etc., but never
  depends back on them (it is a leaf/terminal service — see
  `background-jobs.md` for how business services trigger it without tight
  coupling).

## 4. Centralized Error Handling

`core/exceptions.py` defines a small hierarchy of domain exceptions:

```
FinTrackError (base)
├── NotFoundError          → 404
├── ConflictError          → 409
├── ValidationError        → 422  (business-rule validation, distinct from Pydantic's own 422)
├── UnauthorizedError      → 401
├── ForbiddenError         → 403
├── InsufficientFundsError → 400
└── RateLimitedError       → 429
```

`main.py` registers exception handlers mapping each of these (plus
FastAPI's own `RequestValidationError` and an unhandled-exception
catch-all) to the standard error envelope from root prompt §22:

```json
{
  "error": {
    "code": "ACCOUNT_NOT_FOUND",
    "message": "The requested account was not found",
    "request_id": "..."
  }
}
```

The catch-all handler for truly unexpected exceptions logs the full
stack trace server-side (structured log, with request id) but returns
only a generic `INTERNAL_ERROR` message and the request id to the
client — never a stack trace or internal detail.

## 5. Testability Implications of This Structure

- Services can be unit-tested with a test DB session and no HTTP client
  at all (`tests/unit/`).
- Repositories can be integration-tested directly against a test
  PostgreSQL instance to verify query correctness (`tests/integration/`).
- Full request/response behavior, including auth and error-envelope
  shape, is tested via `httpx.AsyncClient` against the FastAPI app
  (`tests/api/`).
- Because workers call the same service layer as the API, recurring-
  transaction idempotency (`UC-09`) can be tested by calling the service
  method directly and does not require a running Celery worker/broker in
  the test suite.
