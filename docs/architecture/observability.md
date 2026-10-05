# FinTrack — Observability Architecture

## 1. Structured Logging

- Format: JSON, one object per log line (production); a human-readable
  console renderer MAY be used in local dev for readability, backed by
  the same structured event data (`structlog` supports both from one
  configuration).
- Required fields on every request-scoped log line: `timestamp`,
  `level`, `request_id`, `user_id` (when authenticated, else `null`),
  `method`, `path`, `status_code`, `duration_ms`, `event`
  (short message).
- On error: additionally `error_type`, `error_message`, and (server-side
  only, never in the client response) enough context to debug — but never
  request bodies containing passwords/tokens, per the redaction rule in
  `security-architecture.md` §7.
- A `request_id` is generated per request (or taken from an inbound
  `X-Request-ID` header if present, so it can be correlated with an
  upstream load balancer/CDN log) and bound to the logging context for
  the duration of the request via `contextvars`, so every log line
  emitted anywhere during that request — including from the service and
  repository layers — carries it without having to pass it explicitly
  through every function call.
- Background job logs (`background-jobs.md` §5) use the same structured
  format with `task_id` in place of `request_id`.

## 2. Request ID Propagation

- Assigned by middleware, first in the chain (§4 of
  `system-architecture.md`).
- Returned to the client in the `X-Request-ID` response header and in
  every error envelope's `request_id` field, so a user reporting an issue
  can hand over one value that pinpoints the exact log lines.

## 3. Health & Readiness

Two distinct endpoints, intentionally not merged into one, because they
answer different questions an orchestrator needs to ask:

| Endpoint | Question | Checks |
|---|---|---|
| `GET /health` | "Is the process alive and should NOT be restarted?" | Process responds at all. No downstream dependency checks — if this fails, the orchestrator restarts the container, which won't fix a downed database, so it must not depend on one. |
| `GET /ready` | "Should traffic be routed to this instance right now?" | Database connection succeeds (lightweight `SELECT 1`), Redis connection succeeds. If either fails, returns 503 so the load balancer stops routing to this instance until it recovers — without killing/restarting the process. |

Both are unauthenticated, lightweight, and excluded from rate limiting
and from the structured request-logging noise floor (logged at debug
level only, or sampled, to avoid drowning real traffic logs in health
checks).

## 4. Metrics (Prometheus-Compatible)

Exposed at `GET /metrics` in Prometheus text format (via
`prometheus-fastapi-instrumentator` or an equivalent), excluded from
public routing in production (internal-only, scraped by the monitoring
stack, not exposed through the public load balancer listener).

| Metric | Type | Labels | Purpose |
|---|---|---|---|
| `http_requests_total` | Counter | `method`, `path`, `status_code` | Request volume and error rate (4xx/5xx ratio) per endpoint. |
| `http_request_duration_seconds` | Histogram | `method`, `path` | Latency distribution — feeds the p50/p95 targets in `03-non-functional-requirements.md` §1. |
| `db_connection_pool_in_use` / `db_connection_pool_available` | Gauge | — | Early warning for connection pool exhaustion under load. |
| `background_job_duration_seconds` | Histogram | `task_name` | Job latency, to catch a slow-growing task before it times out. |
| `background_job_failures_total` | Counter | `task_name`, `reason` | The primary alerting signal for `background-jobs.md`'s retry/failure policy. |
| `cache_hits_total` / `cache_misses_total` | Counter | `cache_key_prefix` | Validates whether `caching-strategy.md`'s caches are actually earning their keep (ties to Stage 9's acceptance criterion). |
| `rate_limit_rejections_total` | Counter | `endpoint` | Visibility into abuse/brute-force attempts and whether limits are tuned sensibly. |

Path labels use the FastAPI route template (e.g., `/accounts/{id}`), not
the raw URL, to avoid unbounded cardinality from path parameters.

## 5. Error Tracking Approach

- All unhandled exceptions are logged with full stack trace (server-side
  structured log) via the centralized exception handler
  (`component-architecture.md` §4), tagged with `request_id` for
  correlation.
- The architecture is compatible with plugging in a hosted error-tracking
  service (e.g., Sentry) later via its standard logging/ASGI integration,
  but no external error-tracking SaaS is required for v1 — structured
  logs plus the `background_job_failures_total` / error-rate metrics are
  sufficient for a project at this scale, and adding a third-party
  dependency for this would be premature per engineering rule 2.

## 6. What's Explicitly Out of Scope for v1

- **Distributed tracing** (OpenTelemetry spans across service calls): with
  a single deployable and no cross-service network hops, there's no
  distributed call graph to trace — the request-id-correlated structured
  logs already answer "what happened during this request." Would be
  revisited if the architecture ever moved past the modular monolith.
- **A provisioned Grafana/alerting stack**: this document defines what
  metrics *exist* and what they mean; wiring them into a live dashboard
  and paging rules is an operational deployment concern
  (`docs/deployment.md`, Stage 15), not an application architecture
  concern.

## 7. Observability Checklist per Endpoint (Definition of Done addendum)

Every new endpoint added during implementation must, by construction of
the shared middleware/dependencies (not by per-endpoint boilerplate):
- Appear in `http_requests_total` / `http_request_duration_seconds` with
  correct method/path/status labels.
- Emit a structured log line with `request_id` on both success and error.
- Return the standard error envelope (with `request_id`) on failure.

Because these are provided by shared middleware and the centralized
exception handler, no individual router should need to opt in manually —
an endpoint missing observability is a bug in the shared layer, not a
per-endpoint oversight.
