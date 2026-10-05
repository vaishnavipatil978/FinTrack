# FinTrack — Background Job Architecture

## 1. Technology Choice

**Celery + Redis** (Redis as both broker and result backend). Chosen
over alternatives (RQ, Dramatiq, arq) because it's the most
battle-tested Python task queue, integrates cleanly with a Redis instance
we already run for caching/rate-limiting (no new infrastructure
component), and has mature support for retries, exponential backoff, and
scheduled/periodic tasks (Celery Beat) — all of which this project needs.

Per engineering rule 5 ("do not use background jobs for operations that
should be synchronous"), the list below is deliberately short. Creating a
transaction, transfer, budget, or goal is **always synchronous** — the
user is waiting for confirmation and the operation is fast. Background
jobs are used only where there is no request to attach to (scheduled
work) or the operation is bulk/slow enough that blocking an HTTP request
on it would be a poor experience.

## 2. Task Inventory

| Task | Trigger | Why background | Idempotency mechanism |
|---|---|---|---|
| `process_due_recurring_rules` | Celery Beat, daily (configurable, e.g. 00:15 local) | Date-driven, not user-initiated — nothing to attach to synchronously (`FR-RECUR-02`). | DB unique constraint on `(recurring_rule_id, scheduled_date)` — see `data-flow.md` §3. |
| `process_import_batch` | Enqueued by `CsvImportService.confirm()` only when row count exceeds the sync threshold (`FR-CSV-06`) | Large files could take longer than is reasonable to hold an HTTP request open. | Batch `status` transitions (`PENDING_PREVIEW → CONFIRMED/PROCESSING → COMPLETED`) enforced with a guard so the task is a no-op if the batch isn't in `PROCESSING`. |
| `send_notification_email` | Enqueued by `NotificationService` after any in-app notification is created, if the user has the EMAIL channel enabled for that type | Email delivery is a slow, failure-prone I/O call that must not block the request that triggered it (e.g., creating a transaction that happens to exceed a budget). | Not inherently unsafe to retry (sending a duplicate email is undesirable but not data-corrupting); mitigated with Celery's built-in de-dup via task id where the notification id is used as the task's idempotency key. |
| `compute_periodic_summary_snapshot` (optional/P2) | Celery Beat, e.g. nightly | Pre-warms the monthly-report cache for active users so the first request of the day is fast; purely a cache-warming optimization, not required for correctness. | Idempotent by construction — it just overwrites the same cache key. |
| `reconcile_account_balances` (ops/maintenance) | Celery Beat, weekly, or triggered manually | Verifies `accounts.balance` equals `SUM(signed ledger entries)` for every account and logs/alerts on drift, as a safety net for the denormalized-balance invariant in `database-design.md` §1.2. | Read-only; no write unless drift is found, in which case it corrects the balance and logs an audit entry — this path should never fire in normal operation and its firing is itself an alert-worthy signal. |

## 3. Retry & Failure Policy

- Every task defines a bounded max retry count (default: 3) with
  **exponential backoff** (`countdown = base * 2**retry_count`, plus
  jitter) rather than fixed-interval retries, to avoid thundering-herd
  retries after a transient outage (e.g., a brief DB connection blip).
- Retries apply to **transient** failures: DB connection errors, Redis
  connection errors, network errors calling the email provider.
  **Non-transient** failures (a malformed CSV row that will never become
  valid, a recurring rule pointing at a since-archived account) are not
  retried — they're recorded as a permanent failure on the relevant
  entity (`csv_import_rows.status = INVALID`, or a `RECURRING_RULE_FAILED`
  notification/audit entry) and require user or admin action, not a
  retry loop.
- After exhausting retries, a task is marked failed, logged with full
  context (task name, args excluding sensitive data, exception), and
  counted in the `background_job_failures_total` metric
  (`observability.md`) — this is the signal an operator would alert on.
- Failure of one item in a batch (e.g., one bad row in
  `process_import_batch`, one broken rule in
  `process_due_recurring_rules`) does not abort the whole batch — each
  unit of work is processed and committed independently so one failure
  doesn't block unrelated users' recurring transactions or import rows.

## 4. Idempotency Design Principle

Wherever a natural database uniqueness constraint can express "this exact
unit of work has already been done" (recurring occurrences, CSV batch
status transitions), that constraint — not application-level "check then
act" logic — is the source of truth, because it is race-proof under
concurrent workers/retries in a way that a check-then-act read-then-write
sequence is not. Redis-based idempotency keys (`caching-strategy.md` §4)
are used only where no natural DB key exists (arbitrary client-retried
API calls like CSV confirm).

## 5. Job Logging

Every task logs, in structured JSON: task name, task id, args (with
sensitive fields excluded — no amounts/PII beyond ids), start time,
duration, outcome (success/retry/failure), and retry count. This feeds
both the structured logging pipeline and the Prometheus job-failure
counter described in `observability.md`.

## 6. Why Not Used For Everything

Explicitly kept synchronous, per engineering rule 5:
- Creating/updating/deleting a transaction, transfer, budget, or goal.
- Small CSV imports (below the row-count threshold) — the user is
  actively waiting on the import result and it completes in well under a
  second for realistic file sizes.
- Login, registration, token refresh.

If a future load test shows any of these becoming slow enough to justify
async handling, that would be a deliberate, documented architecture
change — not a default.
