# FinTrack — Development Roadmap

This roadmap sequences the 16 development stages defined in the project
brief. Each stage lists scope, dependencies, acceptance criteria, and a
rough effort estimate. Estimates assume focused, incremental work with
tests and docs included in the stage — not a separate "testing phase"
tacked on at the end for that stage's own scope (Stage 12 is reserved for
cross-cutting test hardening across all stages, not first-time test
writing).

**Process rule**: at the end of every stage, implementation stops for
review before the next stage begins. A stage is not "done" until its
acceptance criteria pass, its tests exist and pass, and any relevant doc
under `docs/` is updated.

## Stage Overview

| Stage | Name | Depends On | Est. Effort |
|---|---|---|---|
| 0 | Requirements & Project Definition (this doc set) | — | done (this deliverable) |
| 1 | Project Foundation | 0 | 0.5–1 day |
| 2 | Database Schema & Migrations | 1 | 1–1.5 days |
| 3 | Authentication | 2 | 1.5–2 days |
| 4 | Accounts | 3 | 0.5–1 day |
| 5 | Transactions & Transfers | 4 | 1.5–2 days |
| 6 | Budgets & Goals | 5 | 1–1.5 days |
| 7 | Recurring Transactions (worker) | 5 | 1.5–2 days |
| 8 | CSV Import | 5 | 1–1.5 days |
| 9 | Redis: caching, rate limiting, idempotency | 3, 5 | 1 day |
| 10 | Notifications & Audit Logging | 5, 9 | 1 day |
| 11 | Reporting | 5, 6 | 1 day |
| 12 | Test Hardening (security, concurrency, coverage gaps) | 1–11 | 1–1.5 days |
| 13 | Observability | 1 (extended throughout) | 0.5–1 day |
| 14 | CI/CD | 1–13 | 0.5–1 day |
| 15 | Production Deployment (AWS) | 14 | 1–2 days |
| 16 | Production Readiness Review | 15 | 0.5 day |

Total rough estimate: ~15–20 focused working days for a single engineer.
This is a sizing aid, not a commitment.

---

### Stage 1 — Project Foundation
**Scope**: repo layout (`app/`, `tests/`, `docs/`, `alembic/`, `scripts/`,
`docker/`), `pyproject.toml` with dependencies and tool config, settings
management (pydantic-settings, per-environment config), structured logging
setup, FastAPI app factory, `/health` and `/ready` endpoints, Dockerfile,
docker-compose with FastAPI + PostgreSQL, `.env.example`.
**Acceptance criteria**:
- `docker compose up` brings up the app and PostgreSQL; app connects to the
  DB on startup.
- `GET /health` returns 200 immediately; `GET /ready` returns 200 only
  once the DB connection is confirmed.
- Lint/format/type-check tooling runs cleanly on the (minimal) codebase.

### Stage 2 — Database
**Scope**: SQLAlchemy 2.x models for all core entities (User, Account,
Category, Transaction, Transfer, Budget, Goal, RecurringRule,
RecurringOccurrence, Notification, AuditLog, RefreshToken), Alembic
migrations, indexes/constraints per `docs/database-design.md` (produced in
Phase 1/architecture stage).
**Acceptance criteria**:
- A fresh, empty PostgreSQL database can be brought fully up to date using
  only `alembic upgrade head` — no manual SQL.
- `alembic downgrade` paths exist and are exercised at least once in CI or
  a test.

### Stage 3 — Authentication
**Scope**: registration, login, JWT issuance, refresh token rotation with
reuse detection, logout, password change, forgot-password flow, rate
limiting on auth endpoints (stubbed until Stage 9's Redis lands, or Redis
introduced here if sequencing favors it — see architecture stage for the
final call).
**Acceptance criteria**: covered by `US-AUTH-*` stories; unit + API tests
for happy path, wrong credentials, token rotation, reuse detection, and
rate limiting.

### Stage 4 — Accounts
**Scope**: CRUD + archive for accounts, ownership enforcement, balance
field maintenance.
**Acceptance criteria**: `US-ACCT-*` stories pass; cross-user access
returns 403/404 in tests.

### Stage 5 — Transactions & Transfers
**Scope**: transaction CRUD with atomic balance updates, filtering/
pagination/sorting, transfer creation with atomic two-leg updates and row
locking.
**Acceptance criteria**: `UC-04` and `UC-07` scenarios pass, including the
forced-failure rollback test and the concurrent-transfer test described in
`05-use-cases.md`.

### Stage 6 — Budgets & Goals
**Scope**: budget CRUD, live utilization computation; goal CRUD,
contributions, live progress/required-contribution computation.
**Acceptance criteria**: `UC-06` and `UC-08` scenarios pass; math is unit
tested with fixed inputs/expected outputs (deterministic, no reliance on
"today" without freezing time in tests).

### Stage 7 — Recurring Transactions
**Scope**: recurring rule CRUD, Celery (or chosen queue) worker
infrastructure, scheduled processing job, idempotent occurrence handling.
**Acceptance criteria**: `UC-09` idempotency test (double-invoke same
occurrence → one transaction) passes; worker retry-after-crash simulated
in a test.

### Stage 8 — CSV Import
**Scope**: upload, validation, preview, duplicate detection, confirm/
commit (sync for small files, async job for large files), import report.
**Acceptance criteria**: `UC-10` scenarios pass, including malformed file
rejection and duplicate-confirm not double-importing.

### Stage 9 — Redis
**Scope**: caching for suitable read-heavy endpoints (e.g., report
summaries, category list), Redis-backed rate limiting, idempotency-key
support for unsafe-to-retry endpoints.
**Acceptance criteria**: documented cache keys/TTLs/invalidation in
`docs/architecture/caching-strategy.md`; a basic before/after measurement
showing the cache actually reduces DB load for the cached endpoint(s).

### Stage 10 — Notifications & Audit Logging
**Scope**: `NotificationService` abstraction with in-app + pluggable email
channel; audit log writes on all events listed in `FR-AUDIT-01`.
**Acceptance criteria**: notification and audit concerns are triggered via
a decoupled mechanism (e.g., domain events/hooks called from services),
not hardcoded into every router; audit logs never contain secrets (tested).

### Stage 11 — Reporting
**Scope**: monthly summary, category breakdown, balances overview,
budget/goal snapshot endpoints.
**Acceptance criteria**: `UC-11` passes; query plans checked for N+1
issues; report figures match hand-computed expected values in tests.

### Stage 12 — Testing (cross-cutting hardening)
**Scope**: fill gaps across unit/integration/API/security/concurrency/
background-job categories identified by a coverage review; add
cross-user-access security tests systematically across every resource
type; add load-relevant concurrency tests beyond transfers (e.g.,
concurrent recurring processing).
**Acceptance criteria**: meaningful coverage across all modules (no module
with zero tests); security test matrix (unauthorized, invalid token,
expired token, cross-user, malformed input) applied to every resource
type.

### Stage 13 — Observability
**Scope**: structured JSON logging finalized, request-id middleware,
Prometheus metrics endpoint, dashboards/alerts documented (not necessarily
provisioned in a live Grafana instance, but the metrics must exist).
**Acceptance criteria**: `/metrics` exposes request count/latency/error
counters and background job success/failure counters; logs are JSON with
required fields on both success and error paths.

### Stage 14 — CI/CD
**Scope**: GitHub Actions workflow: install → lint → type-check → unit
tests → integration tests (against a service-container PostgreSQL/Redis)
on every PR; a separate build/push/deploy workflow gated on merge to main.
**Acceptance criteria**: CI passes on a clean PR from a fresh clone; a
failing lint/type/test step blocks merge.

### Stage 15 — Production Deployment
**Scope**: AWS deployment per `docs/deployment.md` (produced alongside
this stage), migrations run against the target DB, environment variables
configured via secrets manager, HTTPS termination, logging/monitoring
wired to the deployed instance.
**Acceptance criteria**: the deployed instance is actually exercised (not
just "should work") — health/ready checks verified live, a full user
journey (register → login → create account → add transaction → view
report) executed against the deployed API.

### Stage 16 — Production Readiness Review
**Scope**: full review against `docs/security-review.md`,
`docs/performance-review.md`, and the Definition of Done checklist (root
prompt section 38).
**Acceptance criteria**: every item in the Definition of Done is either
checked off with evidence (test name, doc link, deployment log) or
explicitly logged as a known, accepted gap with rationale. Only after this
review is the project labeled **Production Ready**.

---

## Immediate Next Step

This document set (Phase 0) is complete. The next stage per the project's
required process is **Phase 1 — Architecture Design**
(`docs/architecture/*.md` + `docs/database-design.md` + `docs/api-design.md`),
which will not begin until this Phase 0 deliverable is reviewed and
approved.
