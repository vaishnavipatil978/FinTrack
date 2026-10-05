# FinTrack — Data Flow

This document traces how data moves through the system for the
highest-risk and most illustrative operations, complementing the use
cases in `05-use-cases.md` with a layer-by-layer view.

## 1. Synchronous Write: Create a Transaction (`UC-04`)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as API Router
    participant Auth as Auth Dependency
    participant TS as TransactionService
    participant AS as AccountService
    participant Repo as Repositories
    participant DB as PostgreSQL

    C->>API: POST /api/v1/transactions {account_id, amount, ...}
    API->>Auth: get_current_user()
    Auth-->>API: current_user
    API->>TS: create_transaction(current_user, payload)
    TS->>AS: get_owned_account(current_user, account_id)
    AS->>Repo: fetch account WHERE id=? AND user_id=?
    Repo->>DB: SELECT
    DB-->>Repo: account row (or none)
    Repo-->>AS: account | None
    AS-->>TS: account (raises NotFoundError if None or archived)
    TS->>DB: BEGIN
    TS->>Repo: insert transaction row
    TS->>Repo: update account.balance (+/- amount)
    Repo->>DB: INSERT, UPDATE
    TS->>DB: COMMIT
    TS->>TS: check budget threshold for category/period
    TS-->>API: TransactionRead
    API-->>C: 201 Created
    Note over TS: audit log write and budget-exceeded<br/>notification are enqueued after commit,<br/>never blocking the response on email/log I/O
```

Key property: the transaction insert and the balance update happen inside
one DB transaction. If either fails, both roll back — the account balance
can never reflect a transaction that doesn't exist, or vice versa.

## 2. Synchronous Write: Transfer Between Accounts (`UC-07`)

```mermaid
sequenceDiagram
    participant C as Client
    participant TFS as TransferService
    participant DB as PostgreSQL

    C->>TFS: create_transfer(user, from_id, to_id, amount)
    TFS->>TFS: validate ownership, currency match, both active
    TFS->>DB: BEGIN
    TFS->>DB: SELECT accounts WHERE id IN (from_id, to_id)<br/>ORDER BY id FOR UPDATE
    Note over TFS,DB: locking order is always ascending account.id,<br/>regardless of which is "from" or "to",<br/>to prevent deadlocks between opposite-direction<br/>concurrent transfers
    TFS->>TFS: check source balance sufficient<br/>(or allow_negative_balance)
    TFS->>DB: INSERT transfers row
    TFS->>DB: INSERT transaction (TRANSFER_OUT, from_account)
    TFS->>DB: INSERT transaction (TRANSFER_IN, to_account)
    TFS->>DB: UPDATE from_account.balance -= amount
    TFS->>DB: UPDATE to_account.balance += amount
    TFS->>DB: COMMIT
    Note over TFS,DB: any failure before COMMIT →<br/>full ROLLBACK, no partial effect visible<br/>to any other transaction (isolation)
```

This is the single most correctness-critical flow in the system and is
covered by a dedicated forced-failure integration test and a concurrency
test (see `05-use-cases.md` UC-07 alternate flows).

## 3. Background Flow: Recurring Transaction Processing (`UC-09`)

```mermaid
sequenceDiagram
    participant Beat as Celery Beat
    participant Worker as Celery Worker
    participant RS as RecurringTransactionService
    participant TS as TransactionService
    participant DB as PostgreSQL

    Beat->>Worker: enqueue "process_due_recurring_rules" (daily)
    Worker->>DB: SELECT rules WHERE status=ACTIVE AND next_run_date <= today
    loop for each due rule
        Worker->>RS: process_occurrence(rule, scheduled_date)
        RS->>DB: BEGIN
        RS->>DB: INSERT recurring_occurrences<br/>(recurring_rule_id, scheduled_date) — UNIQUE constraint
        alt insert succeeds (first time processing this occurrence)
            RS->>TS: create_transaction(...) within same DB transaction
            RS->>DB: UPDATE recurring_rules.next_run_date = next(scheduled_date)
            RS->>DB: COMMIT
            RS->>RS: enqueue notification (async, after commit)
        else unique_violation (already processed — retry/redelivery)
            RS->>DB: ROLLBACK current statement, treat as success no-op
            Note over RS: no duplicate transaction is created
        end
    end
```

The uniqueness constraint on `(recurring_rule_id, scheduled_date)` — not
application-level "check then insert" logic — is what makes this safe
under retries, worker crashes, and at-least-once task redelivery. A
check-then-insert approach would have a race window; the DB constraint
does not.

## 4. Background Flow: CSV Import (`UC-10`)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as API Router
    participant CS as CsvImportService
    participant Worker as Celery Worker (large files only)
    participant DB as PostgreSQL

    C->>API: POST /transactions/import (multipart CSV)
    API->>CS: create_preview(user, file)
    CS->>CS: parse + validate rows (structure, types, dates)
    CS->>DB: INSERT csv_import_batches (PENDING_PREVIEW)
    CS->>DB: INSERT csv_import_rows (VALID/INVALID/DUPLICATE per row)
    CS-->>API: preview summary
    API-->>C: 200 {batch_id, valid, invalid, duplicates}

    C->>API: POST /transactions/import/{batch_id}/confirm {row_ids}
    API->>CS: confirm(user, batch_id, row_ids)
    alt small batch
        CS->>DB: BEGIN
        CS->>DB: INSERT transactions for selected rows,<br/>UPDATE account balances
        CS->>DB: UPDATE batch status=COMPLETED
        CS->>DB: COMMIT
        CS-->>API: final report
        API-->>C: 200 {imported, skipped}
    else large batch (row count > threshold)
        CS->>DB: UPDATE batch status=PROCESSING
        CS->>Worker: enqueue "process_import_batch"(batch_id)
        CS-->>API: accepted
        API-->>C: 202 Accepted {status_url}
        Worker->>DB: BEGIN ... same per-row logic ... COMMIT
        Worker->>DB: UPDATE batch status=COMPLETED
        C->>API: GET /transactions/import/{batch_id}
        API-->>C: 200 {status: COMPLETED, report}
    end
```

The `confirm` step transitions `csv_import_batches.status` from
`PENDING_PREVIEW` → `CONFIRMED`/`PROCESSING`; a second confirm call on an
already-confirmed batch is rejected (409), preventing double-import from
a client retry.

## 5. Read Flow With Cache: Monthly Report

```mermaid
sequenceDiagram
    participant C as Client
    participant RS as ReportService
    participant Cache as Redis
    participant DB as PostgreSQL

    C->>RS: GET monthly-summary(user, month, year)
    RS->>Cache: GET report:{user_id}:{year}-{month}
    alt cache hit
        Cache-->>RS: cached JSON
        RS-->>C: 200 (fast path)
    else cache miss
        RS->>DB: aggregate income/expense/category queries
        DB-->>RS: rows
        RS->>RS: compose report
        RS->>Cache: SET report:{user_id}:{year}-{month} (TTL, see caching-strategy.md)
        RS-->>C: 200
    end
```

Cache invalidation on write: any transaction create/update/delete/void
for a given user invalidates (deletes) that user's cached report keys for
the affected month, rather than relying on TTL alone to catch up — see
`caching-strategy.md` for the full policy.

## 6. Authentication Data Flow (Token Lifecycle)

```mermaid
sequenceDiagram
    participant C as Client
    participant Auth as AuthService
    participant DB as PostgreSQL

    C->>Auth: login(email, password)
    Auth->>DB: SELECT user WHERE email=?
    Auth->>Auth: verify password hash
    Auth->>Auth: issue JWT access token (signed, 15 min)
    Auth->>DB: INSERT refresh_tokens (hashed, new family_id)
    Auth-->>C: {access_token, refresh_token}

    Note over C: access token used as Bearer header<br/>on every subsequent request until it expires

    C->>Auth: refresh(refresh_token)
    Auth->>DB: SELECT refresh_tokens WHERE token_hash=hash(token)
    alt token valid and not revoked
        Auth->>DB: UPDATE revoked_at=now() on old token
        Auth->>DB: INSERT new refresh_tokens row (same family_id, parent=old)
        Auth-->>C: new {access_token, refresh_token}
    else token already revoked (reuse!)
        Auth->>DB: UPDATE revoked_at=now() WHERE family_id=? AND revoked_at IS NULL
        Auth->>DB: INSERT audit_logs (action=REFRESH_TOKEN_REUSE_DETECTED)
        Auth-->>C: 401 — client must log in again
    end
```
