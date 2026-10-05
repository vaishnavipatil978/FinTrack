# FinTrack — Product Requirements Document (PRD)

## 1. Purpose

FinTrack is a personal finance management platform that lets individuals track
their accounts, income, expenses, transfers, budgets, and financial goals in
one place. This document defines the product-level problem, target users,
scope, and success criteria that all downstream engineering decisions
(architecture, API design, data model) must trace back to.

This PRD is an engineering artifact, not a marketing document. It exists to
give the rest of the `docs/` tree — and every implementation stage — a single
source of truth for *what* is being built and *why*.

## 2. Problem Statement

People who want a clear picture of their finances typically resort to
spreadsheets or disconnected banking apps. Spreadsheets don't enforce data
integrity (an account balance can silently go negative, a transfer can debit
one account without crediting another) and banking apps only show one
institution at a time. There is no lightweight, self-hosted-friendly system
that:

- Tracks money across multiple accounts and account types with atomic
  transfers.
- Categorizes spending and enforces budgets per category per month.
- Tracks progress toward savings goals with a clear "required monthly
  contribution" number.
- Automates predictable recurring transactions (rent, salary, EMIs) without
  risking duplicate entries.
- Lets users bulk-import transaction history from their bank's CSV export.
- Treats financial data with the precision and auditability a financial
  system requires (no floating-point rounding errors, an audit trail of
  sensitive actions).

## 3. Product Vision

A secure, API-first personal finance backend that a user (or a future web/
mobile client built on top of it) can rely on as the single source of truth
for "where is my money, where did it go, and am I on track." The system
should be trustworthy in the way a bank's ledger is trustworthy: consistent,
auditable, and never silently wrong.

## 4. Target Users

| User Type | Description |
|---|---|
| **USER** | An individual who registers an account to track their own personal finances: accounts, transactions, budgets, and goals. All data is scoped to this user; a USER can never read or modify another user's data. |
| **ADMIN** | An operator of the platform (not a customer) who can view system-level health, manage user accounts for support purposes (e.g., unlock a locked-out user), and has no implicit access to another user's financial transaction detail beyond what support workflows require. Admin capabilities are intentionally minimal in v1 — this is not an admin-heavy internal tool. |

Out of scope for v1: shared/joint accounts, multi-tenant "household" grouping,
financial advisor or accountant roles with delegated access.

## 5. Goals

1. Give a user an accurate, real-time view of balances across all their
   accounts.
2. Let a user record income, expenses, and inter-account transfers without
   ever leaving the ledger in an inconsistent state.
3. Let a user set monthly category budgets and see utilization/overspend in
   real time.
4. Let a user set savings goals and see progress and required monthly
   contribution.
5. Automate recurring transactions safely (no duplicates, even under retry).
6. Let a user import historical transactions from a CSV export with clear
   validation feedback.
7. Provide monthly financial summaries (income, expense, savings, top
   categories) computed from real data, not hardcoded.
8. Do all of the above with production-grade security, reliability, and
   observability — this is the primary engineering demonstration goal of the
   project.

## 6. Non-Goals (Explicitly Out of Scope for v1)

- No AI/ML features (spend prediction, auto-categorization via ML, chatbots).
- No multi-currency conversion/FX (multi-currency *storage* is supported per
  account, but no cross-currency aggregation or live FX rates in v1).
- No bank account aggregation via Plaid/similar (CSV import only).
- No mobile app or web frontend — this is a backend/API project. A frontend
  may consume the API later but is not built here.
- No microservices split — single modular monolith (see Rule 3 in the
  engineering rules).
- No shared/joint accounts or household-level roles.
- No investment portfolio tracking (stocks, mutual funds) beyond a generic
  "Investment" account type whose balance is manually tracked.

## 7. Success Metrics (Engineering Demonstration Criteria)

Since this is not a live commercial product, "success" is defined by
technical/production-readiness criteria rather than growth metrics:

- All 16 development stages (see `06-development-roadmap.md`) reach their
  acceptance criteria.
- Money is never represented or computed using floating-point types anywhere
  in the codebase.
- A transfer between two accounts is atomic: under any failure mode, either
  both legs are recorded or neither is.
- A recurring transaction job can be retried arbitrarily many times without
  ever creating a duplicate transaction.
- Test suite covers unit, integration, API, security, and concurrency
  scenarios with meaningful (not 100%-for-its-own-sake) coverage.
- CI pipeline (lint, type-check, unit + integration tests) passes on every
  PR.
- The application is deployed, and the deployment — including migrations,
  environment configuration, and health checks — has actually been verified,
  not just documented.
- A documented security review and performance review exist and identified
  risks have mitigations (or explicitly accepted residual risk).

## 8. Assumptions

- Single currency per account; INR is the only currency exercised end-to-end
  in v1, but the schema and service layer must not hardcode INR (a `Currency`
  concept exists from day one).
- Users are individuals managing personal (not business/corporate) finances.
- The platform does not move real money — it is a *record-keeping* system,
  not a payment processor. No integration with payment rails is in scope.
- Email delivery for notifications can be stubbed/mocked in non-production
  environments (e.g., via a console/log backend) — a real SMTP/provider
  integration is not a hard requirement for "done," but the abstraction must
  support plugging one in.

## 9. Constraints

- Backend only: Python 3.12+, FastAPI, PostgreSQL, Redis, SQLAlchemy 2.x,
  Alembic.
- Must run fully locally via Docker Compose with no external paid services
  required for development or testing.
- Must be deployable to AWS using an architecture that is justified, not
  maximal (see `docs/architecture/system-architecture.md`, produced in Phase
  1).

## 10. Key Risks

| Risk | Mitigation |
|---|---|
| Floating-point money bugs | Use `Numeric`/`Decimal` end-to-end; documented in `07` (money handling) and enforced by code review + tests. |
| Non-atomic transfers corrupting balances | Explicit DB transactions with row-level locking on both accounts, tested under concurrency. |
| Recurring job duplicating transactions | Idempotency key per (recurring_rule_id, scheduled_date), unique-constrained at the DB level. |
| Scope creep turning this into a toy CRUD app | Staged development with acceptance criteria per stage; no stage is "done" without tests and docs. |
| Over-engineering (unnecessary microservices/Redis usage) | Explicit engineering rules (see root prompt, section 36) reviewed at each architecture decision. |

## 11. Relationship to Other Documents

- Functional scope is detailed in `02-functional-requirements.md`.
- Quality attributes (performance, security, reliability) are detailed in
  `03-non-functional-requirements.md`.
- User-facing behavior is detailed in `04-user-stories.md` and
  `05-use-cases.md`.
- Delivery plan is detailed in `06-development-roadmap.md`.
