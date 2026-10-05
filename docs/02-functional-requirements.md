# FinTrack — Functional Requirements

Each requirement has a stable ID (`FR-<MODULE>-<NUMBER>`) so it can be
referenced from user stories, API docs, and tests. "MUST" / "SHOULD" /
"MAY" follow RFC 2119 conventions.

## 1. Authentication & Session Management (AUTH)

- **FR-AUTH-01**: The system MUST allow a new user to register with email,
  password, and full name. Email MUST be unique across all users.
- **FR-AUTH-02**: The system MUST hash passwords using a modern adaptive
  hashing algorithm (bcrypt or argon2). Plaintext passwords MUST NEVER be
  stored or logged.
- **FR-AUTH-03**: The system MUST enforce a minimum password policy
  (length, and rejection of extremely common passwords) at registration and
  password-change time.
- **FR-AUTH-04**: The system MUST issue a short-lived JWT access token and a
  longer-lived opaque refresh token upon successful login.
- **FR-AUTH-05**: The system MUST support refresh-token rotation: each use of
  a refresh token invalidates it and issues a new one. Reuse of an already-
  rotated refresh token MUST revoke the entire token family (theft
  detection).
- **FR-AUTH-06**: The system MUST support logout, which revokes the
  presented refresh token (and, optionally, all sessions for that user).
- **FR-AUTH-07**: The system MUST support authenticated password change,
  requiring the current password.
- **FR-AUTH-08**: The system MUST support a "forgot password" flow: request
  a reset token via email, then set a new password using that token. Reset
  tokens MUST be single-use and time-limited.
- **FR-AUTH-09**: The system MUST rate-limit login and password-reset
  request endpoints per IP and per account to mitigate brute-force and
  credential-stuffing attacks.
- **FR-AUTH-10**: The system MUST support email verification after
  registration; unverified accounts MAY have restricted functionality
  (configurable), but registration and login MUST NOT be blocked entirely on
  verification for v1 (documented trade-off, see NFR security section).

## 2. User Profile (USER)

- **FR-USER-01**: An authenticated user MUST be able to view their own
  profile (name, email, created_at, verification status).
- **FR-USER-02**: An authenticated user MUST be able to update their own
  profile (name, default currency, timezone).
- **FR-USER-03**: A user MUST NOT be able to view or modify another user's
  profile under any circumstance.
- **FR-USER-04**: An ADMIN MUST be able to view a user's non-sensitive
  profile and account status (active/locked) for support purposes, but MUST
  NOT be able to read another user's financial transaction detail through an
  admin-only bypass.

## 3. Accounts (ACCT)

- **FR-ACCT-01**: A user MUST be able to create a financial account with a
  name, type (`BANK`, `CASH`, `CREDIT_CARD`, `SAVINGS`, `INVESTMENT`,
  `WALLET`), and currency.
- **FR-ACCT-02**: A user MUST be able to list, retrieve, update, and archive
  (soft-delete) their own accounts.
- **FR-ACCT-03**: An archived account MUST be excluded from active-balance
  aggregations by default but its historical transactions MUST remain
  queryable.
- **FR-ACCT-04**: The system MUST compute an account's current balance from
  its transaction/transfer ledger (or maintain a denormalized balance kept
  consistent via the same DB transaction as ledger writes) — balance MUST
  NEVER drift from the sum of its ledger entries.
- **FR-ACCT-05**: A user MUST NOT be able to view, modify, or delete another
  user's account.
- **FR-ACCT-06**: Deleting (hard-deleting) an account with existing
  transactions MUST NOT be permitted; only archiving is allowed.

## 4. Categories (CAT)

- **FR-CAT-01**: The system MUST provide a set of default system categories
  (e.g., Food, Transport, Salary, Rent, Shopping, Utilities, Entertainment,
  Healthcare, Other) available to every user.
- **FR-CAT-02**: A user MUST be able to create custom categories scoped to
  their own account.
- **FR-CAT-03**: A user MUST be able to update or archive their own custom
  categories; system default categories MUST NOT be editable or deletable by
  users.
- **FR-CAT-04**: Each category MUST have a type consistent with its usage
  (`INCOME` or `EXPENSE`) to prevent nonsensical assignments (e.g., "Salary"
  used on an expense transaction).

## 5. Transactions (TXN)

- **FR-TXN-01**: A user MUST be able to create a transaction of type
  `INCOME` or `EXPENSE` against one of their own accounts, with amount,
  currency, category, date, description, merchant (optional), and notes
  (optional).
- **FR-TXN-02**: Creating a transaction MUST atomically update the affected
  account's balance.
- **FR-TXN-03**: A user MUST be able to update a transaction's mutable
  fields (amount, category, date, description, merchant, notes); updates
  MUST atomically recompute the affected account balance(s).
- **FR-TXN-04**: A user MUST be able to delete (soft-delete/void) a
  transaction; doing so MUST atomically reverse its effect on the account
  balance.
- **FR-TXN-05**: A user MUST be able to list their transactions with
  pagination, filtering (by account, category, type, date range, amount
  range, search text on description/merchant), and sorting (by date, amount).
- **FR-TXN-06**: The amount MUST be a positive decimal value; sign/direction
  is derived from transaction `type`, not from the stored amount.
- **FR-TXN-07**: A user MUST NOT be able to create, view, update, or delete
  a transaction belonging to another user's account.

## 6. Transfers (XFER)

- **FR-XFER-01**: A user MUST be able to create a transfer of a given amount
  from one of their own accounts to another of their own accounts.
- **FR-XFER-02**: A transfer MUST debit the source account and credit the
  destination account atomically — both legs succeed or both are rolled
  back; there MUST be no state where only one leg is applied.
- **FR-XFER-03**: A transfer between accounts of different currencies MUST
  be rejected in v1 (no FX conversion) unless an explicit conversion rate is
  out of scope; same-currency transfers only.
- **FR-XFER-04**: A user MUST be able to list and retrieve their transfer
  history.
- **FR-XFER-05**: A transfer MUST NOT be permitted if it would take the
  source account's balance negative, EXCEPT where the source account type
  permits negative balances (e.g., `CREDIT_CARD`), which MUST be
  configurable per account type.

## 7. Budgets (BUDG)

- **FR-BUDG-01**: A user MUST be able to create a monthly budget for one or
  more categories with a target amount per category.
- **FR-BUDG-02**: The system MUST compute current spending per budgeted
  category for the active period from actual transactions (not manual
  entry).
- **FR-BUDG-03**: The system MUST expose budget utilization (spent /
  target), remaining amount, and an overspend flag when spending exceeds the
  target.
- **FR-BUDG-04**: A user MUST be able to update or delete their own budgets;
  budgets from prior (closed) periods MUST remain viewable as historical
  record.
- **FR-BUDG-05**: A user MUST be able to retrieve a summary across all
  budgeted categories for a given month.

## 8. Financial Goals (GOAL)

- **FR-GOAL-01**: A user MUST be able to create a financial goal with a
  name, target amount, current amount (starting contribution, default 0),
  and target date.
- **FR-GOAL-02**: A user MUST be able to record contributions toward a goal
  (increasing its current amount), optionally linked to a source transaction
  or account.
- **FR-GOAL-03**: The system MUST compute, on read, the goal's progress
  percentage, remaining amount, and the required monthly contribution to
  reach the target by the target date.
- **FR-GOAL-04**: A user MUST be able to update, close, or delete their own
  goals.
- **FR-GOAL-05**: A goal that has reached or exceeded its target amount MUST
  be flagged as achieved.

## 9. Recurring Transactions (RECUR)

- **FR-RECUR-01**: A user MUST be able to define a recurring transaction
  template (amount, account, category, type, description, frequency
  [DAILY/WEEKLY/MONTHLY/YEARLY], interval, start date, optional end date).
- **FR-RECUR-02**: A background worker MUST process due recurring
  transactions on schedule and materialize them as real transactions.
- **FR-RECUR-03**: Processing a recurring transaction MUST be idempotent:
  re-running the job (e.g., after a crash and retry) for the same
  (rule, scheduled occurrence) MUST NOT create a duplicate transaction.
- **FR-RECUR-04**: A user MUST be able to pause, resume, update, or delete a
  recurring transaction rule. Deleting a rule MUST NOT delete transactions
  it already generated.
- **FR-RECUR-05**: A user MUST be able to list upcoming and past occurrences
  generated by a recurring rule.

## 10. CSV Import (CSV)

- **FR-CSV-01**: A user MUST be able to upload a CSV file of transactions
  (columns: date, description, amount, type, category, and optionally
  account, merchant, notes).
- **FR-CSV-02**: The system MUST validate the file structure and row-level
  data (required columns, parseable dates, positive numeric amounts, valid
  type/category values) before import.
- **FR-CSV-03**: The system MUST provide a preview step showing valid rows,
  invalid rows, and specific validation errors per invalid row, without
  committing anything to the database.
- **FR-CSV-04**: The user MUST be able to confirm import of only the valid
  rows (or all rows after fixing/re-uploading).
- **FR-CSV-05**: The system MUST detect likely duplicate rows (same account,
  date, amount, and description already present) and flag them for user
  confirmation rather than silently importing duplicates.
- **FR-CSV-06**: For files above a configurable row-count/size threshold,
  import processing MUST be handled by a background job with a status the
  user can poll, rather than blocking the HTTP request.
- **FR-CSV-07**: The system MUST return a final import report: rows
  imported, rows skipped, and reasons for skips.

## 11. Reporting (RPT)

- **FR-RPT-01**: A user MUST be able to retrieve a monthly summary: total
  income, total expense, net savings, for a given month/year.
- **FR-RPT-02**: A user MUST be able to retrieve spending broken down by
  category for a given period.
- **FR-RPT-03**: A user MUST be able to retrieve current balances across all
  active accounts, individually and aggregated.
- **FR-RPT-04**: A user MUST be able to retrieve budget utilization and goal
  progress as part of, or alongside, the monthly summary.
- **FR-RPT-05**: All report figures MUST be computed from live transactional
  data via the service/query layer — no hardcoded or cached-forever values.

## 12. Notifications (NOTIF)

- **FR-NOTIF-01**: The system MUST generate in-app notifications for
  significant events: budget exceeded, goal achieved, recurring transaction
  processed, large/unusual transaction (configurable threshold).
- **FR-NOTIF-02**: The system SHOULD support email notifications for the
  same events via a pluggable notification channel abstraction; the concrete
  email provider MAY be a no-op/log backend in non-production environments.
- **FR-NOTIF-03**: A user MUST be able to list and mark their notifications
  as read.
- **FR-NOTIF-04**: A user MUST be able to configure which notification types
  they want to receive (opt-out per category).

## 13. Audit Logging (AUDIT)

- **FR-AUDIT-01**: The system MUST record an audit log entry for
  security-sensitive and important business events (see root prompt section
  21 list: LOGIN, LOGOUT, PASSWORD_CHANGED, ACCOUNT_CREATED,
  TRANSACTION_CREATED/UPDATED/DELETED, BUDGET_CREATED, TRANSFER_CREATED,
  GOAL_CREATED, RECURRING_TRANSACTION_PROCESSED, CSV_IMPORTED).
- **FR-AUDIT-02**: Audit log entries MUST capture actor (user id), action,
  entity type/id, timestamp, and request metadata (IP, request id), and MUST
  NOT capture secrets (passwords, tokens, full card numbers).
- **FR-AUDIT-03**: Audit logs MUST be immutable from the application's
  perspective (no update/delete endpoints); only append and read.
- **FR-AUDIT-04**: A user SHOULD be able to view an audit trail of actions
  on their own account (self-service transparency); an ADMIN MAY view audit
  logs across users for investigation purposes.

## 14. Admin (ADMIN)

- **FR-ADMIN-01**: An ADMIN MUST be able to list users and view their
  account status (active, locked, verified).
- **FR-ADMIN-02**: An ADMIN MUST be able to lock/unlock a user account
  (e.g., in response to abuse or a support request).
- **FR-ADMIN-03**: An ADMIN MUST NOT have an endpoint that returns another
  user's plaintext password, active JWT, or full financial transaction
  listing without an explicit, audited support-access justification
  mechanism (out of scope to build the justification workflow in v1; the
  constraint is that no blanket bypass exists).
