# FinTrack — Use Cases

Detailed flows for the system's most important and most failure-prone
operations. Each use case lists actor(s), preconditions, main success
flow, alternate/exception flows, and postconditions. These are the
scenarios that MUST be covered by integration/API tests, not just unit
tests.

---

## UC-01: User Registration → Login

**Actor**: Anonymous visitor (becomes USER)

**Preconditions**: None.

**Main flow**:
1. Client submits `POST /api/v1/auth/register` with email, password, full
   name.
2. System validates input (email format, password policy), checks email
   uniqueness.
3. System hashes the password and creates the user record
   (`is_verified=false`).
4. System creates an audit log entry `ACCOUNT_CREATED`.
5. System (optionally) enqueues a verification email background job.
6. Client submits `POST /api/v1/auth/login` with email, password.
7. System verifies credentials, checks account is not locked.
8. System issues an access token (JWT, short-lived) and a refresh token
   (opaque, stored hashed, longer-lived), creates audit log `LOGIN`.
9. Client stores both tokens.

**Alternate flows**:
- 2a. Email already registered → 409 Conflict, no record created.
- 7a. Wrong password → 401, generic message, failed-attempt counter
  incremented (feeds rate limiting / lockout).
- 7b. Account locked (too many failed attempts) → 403 with a clear
  `ACCOUNT_LOCKED` error code.

**Postconditions**: User exists; client holds a valid access + refresh
token pair.

---

## UC-02: Access Token Refresh with Rotation & Reuse Detection

**Actor**: Authenticated USER (holding a refresh token)

**Preconditions**: User has previously logged in and holds a refresh
token.

**Main flow**:
1. Client's access token expires; client calls
   `POST /api/v1/auth/refresh` with the refresh token.
2. System looks up the refresh token by its hashed value, confirms it is
   not expired, not revoked, and belongs to an active user.
3. System revokes the presented refresh token and issues a new
   access/refresh token pair, linked to the same "token family."
4. Client uses the new pair going forward.

**Alternate flows**:
- 2a. Token not found / expired / already revoked → 401, client must log
  in again.
- 2b. **Reuse detected**: the presented refresh token was valid but had
  already been rotated (i.e., a newer token in its family already exists).
  This indicates possible theft. System revokes the *entire token family*
  (all descendant tokens), logs a security audit event, and returns 401.

**Postconditions**: Either the client has a fresh valid token pair, or (on
reuse detection) all sessions in that family are dead and the user must
re-authenticate, limiting the blast radius of a leaked refresh token.

---

## UC-03: Create an Account

**Actor**: Authenticated USER

**Preconditions**: User is logged in.

**Main flow**:
1. Client calls `POST /api/v1/accounts` with name, type, currency, and
   optional starting balance.
2. System validates input, creates the account owned by `current_user.id`,
   sets balance to the starting balance (default 0).
3. System returns the created account.

**Alternate flows**:
- 1a. Invalid `type` or `currency` → 422 validation error.

**Postconditions**: A new account exists, scoped to the user, immediately
usable as a source/destination for transactions and transfers.

---

## UC-04: Add a Transaction (Expense/Income)

**Actor**: Authenticated USER

**Preconditions**: User owns at least one active account and a valid
category exists.

**Main flow**:
1. Client calls `POST /api/v1/transactions` with account_id, type
   (INCOME/EXPENSE), amount, category_id, date, description.
2. System verifies the account belongs to the current user and is not
   archived; verifies the category is valid for the transaction type.
3. Within a single DB transaction: system inserts the transaction row and
   updates the account's balance (credit for INCOME, debit for EXPENSE).
4. System creates an audit log entry `TRANSACTION_CREATED`.
5. System checks whether this pushes any active budget for that category/
   period over its limit; if so, enqueues a notification.
6. System returns the created transaction (with updated account balance
   available via the account endpoint).

**Alternate flows**:
- 2a. Account not owned by user → 404 (not 403, to avoid confirming
  existence of other users' account IDs).
- 2b. Account archived → 400 `ACCOUNT_ARCHIVED`.
- 3a. Any failure during the DB transaction (e.g., constraint violation)
  → full rollback, no partial balance update, 500/4xx surfaced with a
  request id.

**Postconditions**: Transaction recorded; account balance reflects it
exactly once; budget notification enqueued if applicable.

---

## UC-05: View Balance (Account & Net Worth)

**Actor**: Authenticated USER

**Main flow**:
1. Client calls `GET /api/v1/accounts` (list with balances) or
   `GET /api/v1/reports/balances` (aggregated net worth).
2. System computes/reads balances scoped to `current_user.id`, excluding
   archived accounts from the aggregate by default (with a query flag to
   include them).
3. System returns per-account balances and a total.

**Postconditions**: None (read-only).

---

## UC-06: Create a Budget & Track Spending

**Actor**: Authenticated USER

**Preconditions**: User has at least one category to budget against.

**Main flow**:
1. Client calls `POST /api/v1/budgets` with category_id, target amount,
   period (month/year).
2. System creates the budget scoped to the user.
3. Client calls `GET /api/v1/budgets/{id}` (or the summary endpoint) at any
   point during the period.
4. System computes `spent` by summing EXPENSE transactions in that
   category, owned by the user, within the period's date range; computes
   `remaining = target - spent` and `utilization = spent / target`; flags
   `is_overspent` when `spent > target`.

**Alternate flows**:
- 1a. A budget already exists for that category+period → 409 Conflict
  (use update instead of duplicate create).

**Postconditions**: Budget utilization is always derived live from
transactions — never stored/stale.

---

## UC-07: Transfer Money Between Accounts (Atomicity-Critical)

**Actor**: Authenticated USER

**Preconditions**: User owns both the source and destination accounts;
both accounts share the same currency.

**Main flow**:
1. Client calls `POST /api/v1/transfers` with from_account_id,
   to_account_id, amount, date, description.
2. System verifies both accounts belong to the current user, are active,
   and share currency.
3. System checks the source account's balance permits the transfer (unless
   its account type allows negative balance, e.g. CREDIT_CARD).
4. Within a single DB transaction, using row-level locks (`SELECT ... FOR
   UPDATE`) on both account rows (locked in a consistent order, e.g. by
   account id, to prevent deadlocks): system debits the source account,
   credits the destination account, and inserts a single `Transfer` record
   referencing both legs.
5. System commits the transaction. Both balance changes are now durable
   together.
6. System creates an audit log entry `TRANSFER_CREATED`.

**Alternate flows**:
- 2a. Either account not owned by user, inactive, or currency mismatch →
  4xx, no state changed.
- 3a. Insufficient balance and account type disallows negative → 400
  `INSUFFICIENT_FUNDS`.
- 4a. Any failure mid-transaction (DB error, connection loss) → the entire
  DB transaction rolls back; neither leg is applied. This is verified by a
  dedicated integration test that forces a failure between the two writes
  (e.g., via a mocked repository raising after the first `UPDATE`) and
  asserts both account balances are unchanged afterward.
- 4b. Concurrent transfers touching the same account from two requests →
  the row lock serializes them; the second waits for the first to commit,
  preventing a lost update (tested with a concurrency test issuing
  parallel transfer requests against the same source account and asserting
  the final balance is exactly `initial - sum(transfers)`).

**Postconditions**: Source and destination balances are updated
consistently; the ledger is never observed in a half-applied state by any
other transaction (enforced by DB transaction isolation).

---

## UC-08: Create and Progress a Financial Goal

**Actor**: Authenticated USER

**Main flow**:
1. Client calls `POST /api/v1/goals` with name, target_amount,
   current_amount (default 0), target_date.
2. System creates the goal.
3. Client calls `POST /api/v1/goals/{id}/contributions` with an amount
   (optionally referencing a transaction/account) at any later point.
4. System increases the goal's `current_amount` and records the
   contribution.
5. On any read (`GET /api/v1/goals/{id}`), system computes:
   `progress_pct = current_amount / target_amount`,
   `remaining = target_amount - current_amount`,
   `months_remaining = months_between(today, target_date)`,
   `required_monthly_contribution = remaining / max(months_remaining, 1)`.
6. If `current_amount >= target_amount`, system marks `is_achieved = true`.

**Alternate flows**:
- 5a. `target_date` is in the past and goal not achieved →
  `required_monthly_contribution` is not meaningful; system returns a
  distinct status (e.g., `OVERDUE`) instead of a divide-by-zero or
  negative-months calculation.

**Postconditions**: Goal progress is always derived deterministically from
stored amounts and dates — no hidden mutable "progress" field that can
drift from the underlying numbers.

---

## UC-09: Recurring Transaction Processing (Idempotency-Critical)

**Actor**: System (background worker), configured by USER

**Preconditions**: A recurring rule exists with a due occurrence (e.g.,
next_run_date <= today, status = ACTIVE).

**Main flow**:
1. Scheduler triggers the worker (e.g., daily) to find all recurring rules
   due for processing.
2. For each due rule, the worker computes the specific scheduled occurrence
   key (`recurring_rule_id` + `scheduled_date`).
3. Worker attempts to insert a `Transaction` row AND a
   `RecurringOccurrence` marker row with a UNIQUE constraint on
   (`recurring_rule_id`, `scheduled_date`), inside one DB transaction.
4. If the insert succeeds, the transaction is materialized, the account
   balance updated, and the rule's `next_run_date` advanced.
5. If the unique constraint is violated (occurrence already processed —
   e.g., this is a retry of a previously-successful-but-unacknowledged
   job), the worker treats this as a no-op success and does not create a
   second transaction.
6. Worker creates an audit log entry `RECURRING_TRANSACTION_PROCESSED` and
   enqueues a notification.

**Alternate flows**:
- 3a. DB error mid-transaction → full rollback; the occurrence remains
  "due" and will be retried on the next worker run or scheduled retry,
  safely (per step 5, a retry after partial failure cannot duplicate,
  because nothing was committed).
- Job crashes after commit but before acknowledging to the queue → the
  task queue redelivers the job; step 5's uniqueness check makes the
  redelivery a safe no-op.

**Postconditions**: Exactly one transaction exists per
(recurring_rule_id, scheduled_date), regardless of how many times
processing was attempted. This is verified by a dedicated test that
invokes the processing function twice (or concurrently) for the same due
occurrence and asserts only one transaction was created.

---

## UC-10: CSV Import

**Actor**: Authenticated USER

**Main flow**:
1. Client calls `POST /api/v1/transactions/import` (multipart file
   upload) with a CSV file.
2. System validates file type/size, parses rows, and for each row
   validates: required columns present, date parseable, amount is a
   positive decimal, type is INCOME/EXPENSE, category resolves (by name or
   id) to a valid category for the user.
3. System returns a **preview** response: `valid_rows` (with resolved
   fields), `invalid_rows` (with per-row error messages), and
   `potential_duplicates` (rows matching an existing transaction on
   account+date+amount+description). Nothing is committed yet.
4. Client reviews the preview and calls
   `POST /api/v1/transactions/import/{batch_id}/confirm` specifying which
   rows to actually import (e.g., exclude flagged duplicates).
5. For small batches, system imports synchronously inside a DB transaction
   and returns the final report immediately. For batches over a configured
   row-count threshold, system enqueues a background job and returns a
   `202 Accepted` with a status URL the client polls.
6. System returns the final import report: counts of imported/skipped
   rows and reasons.

**Alternate flows**:
- 2a. Malformed file (not CSV, missing required columns) → 400 with a
  clear structural error before any row-level validation is attempted.
- 4a. `batch_id` references a preview that has expired (e.g., TTL'd out of
  Redis/temp storage) → 410 Gone, client must re-upload.

**Postconditions**: Only explicitly confirmed, valid rows are committed as
transactions; the batch is not silently re-importable (confirming twice
does not double-import, enforced via batch status transition
PENDING → CONFIRMED and idempotency key).

---

## UC-11: Generate Monthly Financial Report

**Actor**: Authenticated USER

**Main flow**:
1. Client calls `GET /api/v1/reports/monthly-summary?month=9&year=2026`.
2. System queries, scoped to the user: sum of INCOME transactions, sum of
   EXPENSE transactions, and derives `savings = income - expense` for that
   date range.
3. System queries spending grouped by category for the same range, sorted
   descending, to surface the top category.
4. System includes budget utilization snapshots and active goal progress
   as of the query time.
5. System returns the composed report.

**Alternate flows**:
- 1a. No transactions in the period → report returns zeroed figures, not
  an error.

**Postconditions**: None (read-only, fully derived from current data — a
report for the same period requested twice with no data changes in
between returns identical figures).
