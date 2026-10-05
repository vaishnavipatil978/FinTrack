# FinTrack — Caching Strategy

Per engineering rule 4 ("do not use Redis unless there is a clear
reason"), every cache entry below is justified individually. If, during
Stage 9 implementation, a before/after measurement shows a cached
endpoint isn't actually meaningfully faster or DB-load-reducing, it is
removed rather than kept for appearance's sake.

## 1. What Is Cached and Why

| Cache Key | Data | Why cache it | TTL | Invalidated by |
|---|---|---|---|---|
| `report:monthly:{user_id}:{year}-{month}` | Monthly summary (income/expense/savings/category breakdown) | Multiple aggregation queries across the transactions table; likely to be viewed repeatedly (e.g., a dashboard) without underlying data changing between views. | 10 minutes | Any transaction create/update/delete/void for that user affecting that month → explicit `DELETE` of the key (write-through invalidation), not just TTL expiry. |
| `report:balances:{user_id}` | Aggregated account balances / net worth | Read on nearly every screen load in a hypothetical client; cheap to compute but frequent enough to matter, and it's a natural pairing with the monthly summary cache. | 2 minutes | Any transaction, transfer, or account create/update for that user → explicit delete. |
| `categories:system` | The list of system default categories (`FR-CAT-01`) | Identical for every user, changes essentially never (only via a deploy-time seed, not a user action). | 1 hour | Manual cache-bust on deploy if the seed set changes; not user-triggered. |
| `budget:utilization:{user_id}:{category_id}:{year}-{month}` | Computed spend/remaining/utilization for one budget | Read on every budget list view; recomputation requires summing transactions for the period. | 5 minutes | Any transaction create/update/delete/void in that category+period, or the budget itself being updated → explicit delete. |

## 2. What Is Deliberately NOT Cached

- **Transaction lists** (`GET /transactions` with filters): too many
  distinct filter/pagination combinations per user for cache keys to be
  effective, and the data is exactly what users expect to see change the
  instant they add something — caching it risks showing stale data on the
  single most frequently mutated resource in the system. Query
  performance here is instead addressed with proper indexes
  (`database-design.md` §3.5), not caching.
- **Account detail / single account reads**: cheap, indexed
  single-row lookups; caching adds invalidation complexity for
  negligible benefit.
- **Goals**: low read frequency and low compute cost relative to the
  complexity of keeping a cached progress figure in sync with
  contributions; not worth it.
- **Anything containing another user's data or cross-user aggregates**:
  cache keys are always scoped by `user_id`, never global, to avoid any
  possibility of a cache-key collision leaking data across users.

## 3. Cache Invalidation Strategy

Two mechanisms, layered:

1. **Write-through invalidation (primary)**: any service method that
   writes data a cache key depends on explicitly deletes the relevant
   key(s) as part of its post-commit steps (same place notifications are
   enqueued — see `data-flow.md` §1). This keeps staleness windows
   effectively zero for normal use.
2. **TTL (safety net)**: every cache key has a bounded TTL regardless of
   invalidation, so a missed invalidation path (bug, or a write path added
   later that forgets to invalidate) self-heals within minutes rather than
   serving stale data indefinitely.

Cache keys always include `user_id` as a namespace segment, both for
correctness (no cross-user leakage) and so a user's cache footprint can be
cleared entirely (e.g., on account deletion) with a key-pattern scan if
ever needed.

## 4. Idempotency Keys (Redis)

Distinct from response caching, but also Redis-backed: certain
state-changing endpoints accept an `Idempotency-Key` header
(`03-non-functional-requirements.md` §4). The service layer:

1. Checks `idempotency:{user_id}:{key}` in Redis.
2. If present, returns the previously stored response instead of
   re-executing the operation.
3. If absent, executes the operation, stores the response under that key
   with a TTL (e.g., 24 hours), and returns it.

Applied to: CSV import batch confirmation (`UC-10`) — a network-retried
confirm must not double-import. Recurring transaction processing does not
need this mechanism because it already has a stronger guarantee: a DB
unique constraint (`database-design.md` §3.11), which is preferred over
Redis-based idempotency wherever a natural database key exists, per the
principle that the source of truth for correctness should be the
database, not a cache that could itself be flushed or expire.

## 5. Rate-Limit Counters (Redis)

Covered in `security-architecture.md` §3. Structurally similar to caching
(Redis key-value with TTL) but conceptually distinct — these keys are
never read as "data," only as counters, and their fail-open behavior on
Redis unavailability is a deliberate availability trade-off already
documented there.

## 6. Measuring Whether Caching Helps (Stage 9 Acceptance Criterion)

For at least the monthly-summary endpoint, Stage 9 implementation
includes a simple before/after comparison (e.g., a local load test or
timed repeated requests) showing cached-hit latency vs. cache-miss/
uncached latency, recorded in the Stage 9 notes. Caching that doesn't
measurably help is a smell, not a feature — it should be removed rather
than left in for its own sake.
