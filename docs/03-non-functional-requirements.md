# FinTrack — Non-Functional Requirements

These define the quality bar the implementation is held to. Where numeric
targets are given, they are realistic for a modular-monolith FastAPI service
backed by a single PostgreSQL instance under moderate personal-finance-app
load — not enterprise-scale figures.

## 1. Performance

| Target | Value |
|---|---|
| p50 API response time (simple reads, e.g. get account) | < 100ms |
| p95 API response time (simple reads) | < 300ms |
| p95 API response time (list/filter endpoints with pagination) | < 500ms |
| p95 API response time (report/aggregation endpoints) | < 800ms |
| Default page size / max page size | 20 / 100 |
| Sustained concurrent requests (single app instance, local benchmark) | 50–100 req/s |
| Database query budget per request (non-report endpoints) | ≤ 5 queries; N+1 patterns are treated as bugs |

Rationale: personal-finance workloads are read-heavy but low-volume per user
(hundreds to low-thousands of transactions per user, not millions). These
targets are meant to catch regressions (N+1 queries, missing indexes), not to
simulate a bank-scale ledger.

## 2. Availability

- Target: 99.5% availability for a single-region deployment (roughly ≤ ~3.6
  hours of downtime/month) — appropriate for a portfolio/demonstration
  production deployment, not a claim of banking-grade SLA.
- The application MUST expose `/health` (liveness: process is up) and
  `/ready` (readiness: DB and Redis reachable) separately so an orchestrator
  can distinguish "restart me" from "don't route to me yet."
- Graceful degradation: if Redis is unavailable, the application MUST
  continue serving requests without caching/rate-limiting rather than
  hard-failing (rate limiting SHOULD fail open with logging, not fail closed
  and block all traffic — documented trade-off, revisited in the security
  review).
- If the background worker is down, synchronous operations (creating
  transactions, transfers, budgets) MUST continue to work; only
  worker-dependent features (recurring processing, async CSV import, async
  notifications) are affected.

## 3. Security

- **Passwords**: hashed with bcrypt or argon2, never logged, never returned
  in any API response.
- **JWT**: short-lived access tokens (target: 15 minutes), signed with a
  strong secret/algorithm (HS256 minimum, RS256 preferred if key rotation is
  implemented), validated on every request via a dependency, and MUST
  include minimal claims (subject/user id, expiry, token type) — no
  sensitive data in the payload.
- **Refresh tokens**: opaque, stored hashed in the database (never stored or
  compared in plaintext), long-lived (target: 7–30 days, configurable),
  rotated on every use, with reuse-detection revoking the token family.
- **Authorization**: every resource access MUST verify the requesting user
  owns the resource (or is an ADMIN performing an explicitly admin-scoped
  action). This MUST be enforced at the service layer, not just by
  filtering in the query (defense in depth: query filters by owner AND a
  404/403 is returned on cross-user access attempts).
- **Input validation**: all request bodies/query params validated via
  Pydantic schemas; no raw dict access to untrusted input in business logic.
- **SQL injection prevention**: all database access via SQLAlchemy's
  parameterized query construction; no raw string-interpolated SQL.
- **Rate limiting**: applied to authentication endpoints (login, register,
  password reset) and, more loosely, to the general API, backed by Redis.
- **CORS**: explicit allow-list of origins via configuration; no wildcard
  `*` origin in production configuration.
- **Secure headers**: standard hardening headers (HSTS, X-Content-Type-
  Options, X-Frame-Options, Referrer-Policy) applied via middleware.
- **Secrets management**: all secrets (DB credentials, JWT signing key,
  Redis credentials, email provider credentials) come from environment
  variables / a secrets manager in production; never committed to source
  control. `.env.example` documents required variables with placeholder
  values only.
- **Sensitive data handling**: financial amounts and personally identifying
  fields are never written to application logs; audit logs capture
  actions/metadata, not raw sensitive payloads.

## 4. Reliability

- **Database transactions**: any operation that touches more than one
  ledger-affecting row (transfers, transaction create/update/delete against
  account balances) MUST run inside a single DB transaction with appropriate
  row locking to prevent lost updates under concurrency.
- **Idempotency**: state-changing endpoints that are unsafe to double-submit
  (e.g., CSV import confirmation, recurring transaction processing) MUST
  support an idempotency key or an equivalent natural-key uniqueness
  constraint so retries are safe.
- **Retries**: background jobs MUST retry transient failures (DB connection
  blips, transient Redis errors) with exponential backoff and a bounded
  maximum attempt count, after which the job is marked failed and logged/
  alerted rather than retried forever.
- **Failure handling**: a failed background job MUST NOT leave partial state
  (e.g., a half-processed CSV import); processing is wrapped in a DB
  transaction per unit of work.
- **Duplicate request handling**: client-side retries of a request that
  already succeeded (e.g., due to a network timeout) MUST NOT create
  duplicate financial records for idempotency-key-protected endpoints.

## 5. Maintainability

- Clean, layered architecture: API (routers) → Service (business logic) →
  Repository/Data-access → Database. Routers MUST NOT contain business
  logic; services MUST NOT construct HTTP-specific objects.
- Full type hints throughout the codebase; `mypy` runs in CI.
- Pydantic v2 schemas for all request/response models, separate from
  SQLAlchemy ORM models (no leaking ORM models directly into API responses).
- Dependency injection via FastAPI's `Depends` for DB sessions, current
  user, and service instances — enabling straightforward test substitution.
- Centralized exception handling: domain exceptions are translated to
  consistent HTTP error responses in one place, not scattered `try/except`
  blocks per router.
- Code formatted and linted consistently (black, ruff) and enforced via
  pre-commit and CI, not left to convention.

## 6. Scalability (documented, not over-built for v1)

- The application MUST be stateless at the process level (no in-memory
  session state) so multiple instances can run behind a load balancer.
- Horizontal scaling is achieved by running more app containers; vertical
  scaling of PostgreSQL is the initial path for database growth. Read
  replicas / sharding are explicitly out of scope for v1 and would only be
  considered if real load data justified it (see engineering rule 2: don't
  over-engineer).

## 7. Observability

- Structured (JSON) logs including timestamp, request id, user id (when
  authenticated), endpoint, status code, duration, and error detail when
  present.
- Prometheus-compatible `/metrics` endpoint exposing request count, request
  latency histograms, error count, DB connection pool health, and background
  job success/failure counts.
- Every request MUST be tagged with a request id (generated or propagated
  from an incoming header) that appears in logs and in the error response
  body for support correlation.

## 8. Compliance & Data Handling (lightweight, documented posture)

- This is not a regulated financial institution and does not claim PCI-DSS
  or banking-license compliance; no raw card numbers are ever collected
  (users record that a credit card *account* exists, not its number).
- Personal data (email, name) is treated as PII: not logged in plaintext
  outside of what's necessary for account identification in audit logs.
- Data retention: soft-deleted (archived) records are retained indefinitely
  in v1 for audit purposes; a hard-delete/GDPR-style erasure workflow is
  documented as a future improvement, not built in v1.

## 9. Testability

- Every business rule with financial impact (balance updates, transfer
  atomicity, budget utilization math, goal progress math, recurring
  idempotency) MUST have unit and/or integration test coverage.
- The test suite MUST be runnable against an isolated test database (not the
  dev database) and MUST NOT require external network access.
