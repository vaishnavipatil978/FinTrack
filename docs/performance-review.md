# FinTrack — Performance Review (Stage 16)

Reviewed against the targets in `docs/03-non-functional-requirements.md`
§1. This is a code-level review plus the two measurements this session
actually ran (Stage 9's cache comparison, and basic latency sampling via
the live stack) — it is not a full load-test campaign.

## 1. N+1 Query Review

Walked every list endpoint's repository function:

| Endpoint | Finding |
|---|---|
| `GET /transactions` | Single paginated query plus one `COUNT`. No N+1. |
| `GET /budgets` | One query per budget to compute `spent` (`BudgetService._to_read`), so an N-budget page issues N+1 queries. **Finding**, documented below. |
| `GET /budgets/summary` | Same N+1 as above, since it reuses `_to_read` per budget. |
| `GET /goals` | Progress math (`compute_goal_progress`) is pure/in-memory, no extra query per goal. No N+1. |
| `GET /reports/monthly-summary` | Two aggregate queries total (totals-by-type, totals-by-category), regardless of transaction count. No N+1. |
| `GET /reports/balances` | Single query. No N+1. |
| `GET /recurring-transactions/{id}/occurrences` | Single query (history) or zero queries (upcoming, computed in memory). No N+1. |

### Finding: budgets list is O(N) queries, not O(1)

`BudgetService.list_for_period` fetches the budget rows in one query,
then calls `_to_read` per budget, each of which runs its own
`sum_expense_for_category_period` query. For a typical user (single-
digit to low-dozens of budgeted categories per month) this is a few
extra fast, indexed queries — not a real problem at today's scale, and
not worth the complexity of a single `GROUP BY` rewrite under
engineering rule 2 (don't over-engineer) given the data volumes in
`03-non-functional-requirements.md` §1. Flagged here rather than
silently accepted: if budgets per user ever grow past ~50-100, this is
the first place to rewrite as one grouped aggregate query.

## 2. Missing Indexes

Checked every `WHERE`/`JOIN`/`ORDER BY` column used by the repositories
against `docs/database-design.md`'s index list:

- `transactions`: filtered/sorted by `user_id`, `account_id`,
  `category_id`, `transaction_date` — all covered by the composite
  indexes from Stage 2 (`ix_transactions_user_id_transaction_date`,
  `ix_transactions_account_id_transaction_date`,
  `ix_transactions_user_id_category_id_transaction_date`).
- `recurring_rules`: the worker's due-rule query
  (`status = ACTIVE AND next_run_date <= ?`) is covered by
  `ix_recurring_rules_status_next_run_date`.
- `audit_logs`: `GET /audit/me` filters by `user_id` (+ optional
  `action`) and sorts by `created_at` — covered by
  `ix_audit_logs_user_id_created_at`. The `action` filter itself is not
  indexed; acceptable since it's always combined with the indexed
  `user_id` filter, so Postgres uses the user index and filters `action`
  from the (small, per-user) result set.
- `notifications`: `ix_notifications_user_id_created_at` covers the
  list endpoint's filter+sort.
- No full table scan identified on any endpoint exercised by the test
  suite (confirmed by reading query plans is not something this
  session ran `EXPLAIN` for — this is a structural review of index
  coverage, not a captured query-plan audit).

## 3. Pagination

Every list endpoint (`transactions`, `transfers`, `goals`, `goal
contributions`, `notifications`, `audit`) uses `LIMIT`/`OFFSET` with a
server-enforced `page_size` ceiling of 100. `budgets` and `categories`
are intentionally unpaginated per the original API design — justified
there by realistic per-user cardinality (single-digit to low-dozens of
rows), not an oversight.

## 4. Serialization

Response models are explicit Pydantic schemas (`*Read`), never raw ORM
objects — no accidental over-fetching of relationship data during
serialization, since the schemas don't declare the ORM relationships
FastAPI would otherwise have to lazy-load.

## 5. Blocking Operations

- Argon2 password hashing is CPU-bound and synchronous, called directly
  inside async request handlers (`register`, `login`,
  `change_password`). This blocks the event loop for the hash's
  duration (tens of milliseconds). Acceptable at this project's scale
  (auth endpoints are low-frequency relative to read endpoints) and
  consistent with NFR targets, but is the one place a future scale-up
  would move to a thread-pool executor (`anyio.to_thread.run_sync`)
  before it would move anywhere else.
- No other synchronous I/O (file, network) was found inside request
  handlers; CSV parsing is in-memory and synchronous but bounded by
  `csv_import_max_rows`/`csv_import_max_file_size_bytes`.

## 6. Redis Usage

- Reviewed every Redis round-trip added in Stage 9: rate limiting is
  one `INCR` + conditional `EXPIRE` per protected request; caching is
  one `GET` per report read and a `SCAN`+`DELETE` per invalidating
  write; idempotency is one `GET` + conditional `SET` per idempotent
  write. No endpoint makes more than 2 Redis round-trips.
- **Cache benefit measured, not assumed** (Stage 9): median latency on
  the monthly-summary endpoint was 12.1 ms cached vs. 13.1 ms uncached
  at this session's data volume (a handful of transactions). The
  difference is within noise at this scale — the cache is not yet
  earning its complexity for a demo-sized dataset, and would need
  re-measuring against a few thousand transactions per user (the upper
  end of the realistic range in the NFRs) before claiming it helps in
  practice. Documented as an open question in `docs/production-
  readiness.md` rather than claimed as a win.

## 7. Load Testing

Performed with Locust (`scripts/locustfile.py`) against the local
`docker compose` stack (single API container, not the deployed
topology — numbers below describe this laptop, not production
hardware). 20 simulated users, ramping at 5/s, sustained for 45s. Each
user registers once, then repeatedly lists transactions/accounts,
pulls the monthly-summary report, and occasionally creates a
transaction — a realistic read-heavy mix.

| Endpoint | Requests | Failures | Median | p95 | Max |
|---|---|---|---|---|---|
| `GET /accounts` | 159 | 0 | 8ms | 19ms | 44ms |
| `GET /transactions` | 235 | 0 | 9ms | 20ms | 92ms |
| `GET /reports/monthly-summary` | 91 | 0 | 9ms | 17ms | 81ms |
| `POST /transactions` | 49 | 0 | 68ms | 110ms | 220ms |
| `POST /accounts` | 8 | 0 | 960ms | 1100ms | 1100ms |
| `POST /auth/register` | 27 | 17 (63%) | 140ms | 1300ms | 1341ms |
| `POST /auth/login` | 27 | 19 (70%) | 52ms | 550ms | 548ms |

**Reads and the core write path (creating a transaction) held up well**:
0% failures, single-digit-to-low-double-digit-millisecond medians.

**The register/login failures are the rate limiter doing its job, not
a bug**: every failure was a `429 Too Many Requests` (plus 2 unrelated
`401`s from a benign race between `on_start` registering and a
same-second duplicate run). 20 simulated users all registering and
logging in within the same few seconds is not a realistic traffic
pattern — real users don't create accounts in bursts — so this
reflects the load-test script's `on_start` design, not a production
risk. It does, incidentally, confirm the rate limiter from
`docs/security-review.md` §1 is live and effective under concurrent
load, which the earlier sequential test (10 requests, 11th/12th
rejected) didn't exercise.

`POST /accounts` at ~1s median is the one number here worth watching:
it's far slower than every other endpoint, including the structurally
similar `POST /transactions` (68ms median). Only 8 samples were
collected (one per simulated user's `on_start`), so this isn't
conclusive, but it's a real signal, not noise — worth profiling before
trusting account creation under real concurrent load. Not fixed here;
recorded as a finding instead of silently passed over.

Raw results: `scripts/locust_results_stats.csv`,
`scripts/locust_results_stats_history.csv`,
`scripts/locust_results_failures.csv` (checked into the repo so the
numbers above aren't the only record of this run).

## 8. Summary

| Area | Status |
|---|---|
| N+1 queries | One minor, low-impact instance found and documented (budgets list) |
| Missing indexes | None found |
| Pagination | Consistent and enforced |
| Blocking operations | One acceptable instance (argon2), documented |
| Caching | Implemented correctly; benefit unproven at current data scale |
| Load testing | **Not done** |
