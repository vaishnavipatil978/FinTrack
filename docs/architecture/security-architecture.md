# FinTrack — Security Architecture

This expands `03-non-functional-requirements.md` §3 into concrete
mechanisms. It is the design that Stage 3 (Authentication) and Stage 12
(security test hardening) implement against, and the baseline
`docs/security-review.md` (produced later, per root prompt §32) is
measured against.

## 1. Authentication

### 1.1 Password storage
- Algorithm: **argon2id** (preferred) via `passlib`/`argon2-cffi`, bcrypt
  as an acceptable fallback if argon2 tooling is unavailable in the target
  environment. Work factor set to current OWASP-recommended defaults.
- Passwords are never logged, never included in audit log metadata, never
  returned in any response, and never compared in plaintext (only via the
  hashing library's constant-time verify function).

### 1.2 Access tokens (JWT)
- Algorithm: HS256 with a strong, environment-provided secret (minimum
  256-bit). RS256 is a documented upgrade path if key rotation without
  invalidating a shared secret becomes a requirement — not built in v1.
- Claims: `sub` (user id), `role`, `exp`, `iat`, `jti`, `type: "access"`.
  No email, name, or other PII in the payload — JWTs are base64, not
  encrypted, and must be treated as readable by the client.
- Lifetime: 15 minutes (configurable via settings).
- Validated on every request via a FastAPI dependency
  (`get_current_user`) that verifies signature, expiry, and `type`
  claim (rejects a refresh token presented as an access token, and vice
  versa).

### 1.3 Refresh tokens
- Opaque, high-entropy random string (not a JWT) — the server is the only
  party that needs to interpret it, so there's no reason to make it
  self-describing or expose its structure.
- Stored **hashed** (SHA-256) in `refresh_tokens.token_hash`; the raw
  value is returned to the client exactly once, at issuance, and never
  persisted anywhere in recoverable form.
- **Rotation with reuse detection** (`UC-02`): every refresh call
  invalidates the presented token and issues a new one in the same
  `family_id`. Presenting an already-revoked token revokes the entire
  family — this bounds the damage from a stolen refresh token to the
  window before its first use by the legitimate client or the attacker,
  whichever happens first.
- Lifetime: 7–30 days (configurable). Server-side revocation (logout,
  reuse detection, password change, admin lock) is authoritative — a
  refresh token being "unexpired" is necessary but not sufficient; it must
  also be unrevoked.

### 1.4 Password change / reset
- Changing a password (authenticated) requires the current password and,
  on success, SHOULD revoke all existing refresh token families for that
  user (force re-login on other devices) — configurable, defaulting to on,
  since an attacker who has a stale session but not the new password
  should not retain access.
- Forgot-password reset tokens are single-use, short-lived (e.g., 30–60
  minutes), stored hashed, and the "request reset" endpoint response is
  identical whether or not the email exists (prevents email enumeration).

### 1.5 Account lockout
- After N consecutive failed login attempts (configurable, e.g. 5), the
  account is locked (`is_locked = true`) for a cooldown period or until
  an explicit unlock (self-service via password reset, or admin action).
  This is layered with Redis-backed rate limiting (§3), not a replacement
  for it — rate limiting slows the attempt rate; lockout stops a
  successful-guess race outright.

## 2. Authorization

- **Model**: coarse-grained RBAC (`USER` / `ADMIN`) combined with
  fine-grained **ownership checks** on every resource. RBAC alone is
  insufficient here — the interesting authorization question for almost
  every endpoint is not "is this a USER" (nearly everyone is) but "does
  this USER own this specific account/transaction/budget/goal."
- **Enforcement point**: ownership checks live in the **service layer**,
  not just as a `WHERE user_id = ?` filter that silently returns empty
  results. A request for another user's resource by ID returns **404**
  (not 403) so the response does not confirm the resource exists under
  someone else's account — consistent across every module.
- **Defense in depth**: the repository query itself is also always scoped
  by `user_id` (per `database-design.md` §1.4) — even if a service-layer
  check were ever missed, the query could not return another user's row.
  Two independent layers must both fail for cross-user access to succeed.
- **Admin scope**: admin-only endpoints (`FR-ADMIN-*`) are protected by a
  separate `require_admin` dependency and are deliberately narrow (list
  users, lock/unlock) — there is no generic "admin can do anything any
  user can do" backdoor, per `FR-ADMIN-03`.

## 3. Rate Limiting

- Backed by Redis, using a sliding-window or token-bucket counter keyed
  by `(ip, endpoint)` and, where authenticated, also by `(user_id,
  endpoint)`.
- Applied strictly to: `/auth/login`, `/auth/register`,
  `/auth/forgot-password`, `/auth/reset-password`, `/auth/refresh`.
- Applied loosely (higher threshold) to the general authenticated API as
  a defense against runaway/abusive clients.
- **Fail-open policy**: if Redis is unavailable, rate limiting logs a
  warning and allows the request rather than blocking all traffic (see
  NFR-Availability §2) — a documented, deliberate trade-off between
  strict brute-force protection and overall availability, revisited in
  `docs/security-review.md`.

## 4. Input Validation & Injection Prevention

- Every request body/query/path parameter is validated through a Pydantic
  v2 schema before it reaches business logic — no raw
  `request.json()`/dict access in routers or services.
- All database access goes through SQLAlchemy's query builder / ORM with
  bound parameters. Raw SQL (if ever needed for a complex report query)
  uses `sqlalchemy.text()` with bound parameters only — string
  interpolation into SQL is prohibited and flagged in code review.
- File upload validation (CSV import): content-type and extension check,
  file-size cap, row-count cap for synchronous processing, and structural
  validation before any row is treated as data (`UC-10`).

## 5. Transport & HTTP-Level Hardening

- HTTPS enforced at the load balancer (production); local dev may run
  plain HTTP.
- CORS: explicit origin allow-list from configuration; no `*` in
  production; credentials (`Authorization` header) require an explicit
  origin match, not a wildcard.
- Security headers middleware sets: `Strict-Transport-Security`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, and a conservative `Content-Security-
  Policy` appropriate for a pure JSON API (no inline script concerns, but
  set defensively).
- CSRF: not applicable in the traditional cookie-session sense, since
  authentication is via a Bearer token in the `Authorization` header (not
  an ambient cookie) — this is a deliberate design choice that sidesteps
  CSRF rather than requiring token-based CSRF mitigation. If a future
  browser client stores the refresh token in a cookie for XSS mitigation,
  CSRF mitigations (`SameSite=Strict`, double-submit token) would need to
  be added at that time; documented as a future consideration.

## 6. Secrets Management

- No secret (DB password, JWT signing key, Redis credentials, email
  provider credentials) is ever committed to source control.
- Local/dev: `.env` file (git-ignored), documented via `.env.example`
  with placeholder values.
- Production: environment variables injected by the deployment platform,
  sourced from AWS Secrets Manager or SSM Parameter Store (finalized in
  `docs/deployment.md`) — never baked into the Docker image.
- Settings are loaded via `pydantic-settings`, which fails fast at
  startup if a required secret is missing, rather than falling back to an
  insecure default in production.

## 7. Sensitive Data Handling

- Passwords, raw JWTs/refresh tokens, and full request/response bodies
  containing them are excluded from structured logs by field-level
  redaction in the logging middleware.
- Audit log `metadata` is populated from an explicit allow-list of fields
  per action type (`FR-AUDIT-02`) — never a raw dump of the request body,
  precisely to prevent secrets from leaking into audit records as new
  endpoints are added.
- Error responses never include stack traces or internal exception text;
  only `code`, `message`, and `request_id` (§4 of
  `component-architecture.md`).

## 8. Threat Model Summary (STRIDE-lite)

| Threat | Primary Mitigation |
|---|---|
| **Spoofing** (credential theft, session hijack) | Hashed passwords, short-lived JWTs, rotating refresh tokens with reuse detection, rate limiting, account lockout. |
| **Tampering** (modifying another user's data, altering amounts in transit) | HTTPS, ownership checks at service + query layer, Pydantic validation, DB constraints (`CHECK amount > 0`). |
| **Repudiation** (user denies performing an action) | Audit log on every sensitive action with actor, timestamp, request id. |
| **Information Disclosure** (cross-user data leak, verbose errors) | 404-not-403 on cross-user access, centralized error handling with no stack traces, PII/secret redaction in logs. |
| **Denial of Service** (brute force, resource exhaustion via large CSV) | Rate limiting, account lockout, file size/row caps, async processing for large imports. |
| **Elevation of Privilege** (USER reaching ADMIN endpoints, forging role claim) | Role checked server-side from the DB-backed JWT claim + dependency, not trusted from client input; admin endpoints behind a separate dependency. |

This threat model is revisited and expanded in `docs/security-review.md`
at Stage 16, once the full implementation exists to review against.
