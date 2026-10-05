# FinTrack — Security Review (Stage 16)

Reviewed against the threat model and controls committed to in
`docs/architecture/security-architecture.md`. Each row states what was
actually checked, not just what was designed.

## 1. Authentication

| Control | Status | Evidence |
|---|---|---|
| Passwords hashed with argon2id, never logged/returned | ✅ Verified | `app/core/security.py`; `tests/unit/test_security.py` asserts the hash isn't the plaintext and isn't returned by `/auth/register` |
| JWT access tokens short-lived, signed, minimal claims | ✅ Verified | 15 min default; claims are `sub`/`role`/`type`/`iat`/`exp`/`jti` only |
| Refresh tokens opaque, hashed at rest, rotated with reuse detection | ✅ Verified | `tests/api/test_auth.py::test_refresh_token_reuse_revokes_the_whole_family` - replaying an already-rotated token revokes every descendant token, including ones issued after it |
| Account lockout after repeated failed logins | ✅ Verified | `test_account_locks_after_max_failed_attempts`; self-service recovery via password reset confirmed in `test_reset_password_unlocks_a_locked_account` |
| Forgot-password does not leak whether an email exists | ✅ Verified | `test_forgot_password_responds_identically_for_unknown_email` |
| Rate limiting on login/register/refresh/reset | ✅ Verified | Unit/integration tests in `tests/integration/test_redis_features.py`; also exercised live against the running stack (10 requests pass, 11th/12th return 429) |

## 2. Authorization

| Control | Status | Evidence |
|---|---|---|
| Every resource scoped by owner at the repository query level | ✅ Verified by code review | every `get_owned`/`get_owned_*` repository function filters by `user_id` in the `WHERE` clause, not just in the service layer |
| Cross-user access returns 404, never 403 or the other user's data | ✅ Verified | dedicated cross-user tests exist for accounts, categories, transactions, transfers, budgets, goals, recurring rules, CSV batches, notifications, and reports |
| Admin endpoints are narrow, no blanket bypass | ✅ Verified | `app/api/v1/admin.py` implements `FR-ADMIN-01/02/03`: list/search users, lock/unlock, cross-user audit view - all behind `require_admin`. No admin endpoint returns another user's financial data, password hash, or active token; lock revokes all refresh tokens immediately; self-lock is rejected; both lock and unlock are idempotent. Covered by `tests/api/test_admin.py` (8 tests, run against the real stack) |
| Unauthorized/malformed/expired tokens rejected before touching a resource | ✅ Verified | `tests/api/test_security_matrix.py` sweeps every protected GET/POST with no token, a garbage token, and (on a sample) an expired token |

## 3. Input Validation & Injection

| Control | Status | Evidence |
|---|---|---|
| All request bodies validated via Pydantic before reaching business logic | ✅ Verified by code review | no router accesses a raw request body; every write endpoint takes a typed Pydantic model |
| No raw/string-interpolated SQL anywhere | ✅ Verified by code review | every repository uses SQLAlchemy Core/ORM constructs; the one place a `text()` literal appears (the category-seed downgrade in Alembic) uses a bound parameter, not interpolation |
| CSV upload validated (type, size, structure, per-row fields) before any row is treated as data | ✅ Verified | `tests/api/test_csv_import.py` covers non-CSV extension, missing columns, non-UTF-8 content, empty file, and per-row validation errors |

## 4. Transport & Secrets

| Control | Status | Evidence |
|---|---|---|
| Security headers set (HSTS prod-only, nosniff, frame-deny, CSP) | ✅ Verified | `tests/api/test_platform.py::test_security_headers_are_set`; HSTS confirmed absent outside production |
| CORS has no wildcard in production | ✅ Verified | `Settings._production_guards` raises at startup if `cors_origins` contains `*` in production; unit-tested |
| `jwt_secret_key` required, ≥32 chars enforced in production | ✅ Verified | unit-tested in `tests/unit/test_config.py` |
| No secret committed to the repo | ✅ Verified | `.env` is git-ignored; `.env.example` holds placeholders only; `docker-compose.yml` reads secrets from the environment with a clearly-marked dev-only fallback |

## 5. Sensitive Data Handling

| Control | Status | Evidence |
|---|---|---|
| Audit log metadata is allowlisted, never a raw body dump | ✅ Verified | `tests/unit/test_audit_allowlist.py`: a password/token passed into `metadata` is dropped before the row is written |
| Audit trail never exposes a password/token when read back | ✅ Verified | `tests/api/test_audit_and_notifications.py::test_audit_entries_never_contain_secrets` |
| Unhandled exceptions never leak a stack trace to the client | ✅ Verified | `test_unhandled_error_does_not_leak_internals` |

## 6. Residual Risks (Accepted, Not Mitigated)

These are documented trade-offs from `security-architecture.md`, re-affirmed
here rather than silently left in place:

1. **Rate limiting fails open** if Redis is unreachable. A Redis outage
   during an active credential-stuffing attempt would remove the rate
   limit (account lockout still applies independently). Accepted per
   the availability-vs-strict-brute-force-protection trade-off
   documented in the NFRs; revisit if this product ever handles
   financial transfers of real money rather than record-keeping.
2. **No CSRF-specific mitigation.** Not applicable as built: auth is a
   Bearer token in the `Authorization` header, not an ambient cookie,
   so there is no CSRF attack surface today. Would need revisiting if
   a future browser client ever moves the refresh token into a cookie.
3. **Admin role enforcement** is now reviewed (see §2) - no change to
   this list beyond removing it as an open item.
4. **Idempotency/rate-limit/cache fail open on Redis failure** by
   design (documented in `caching-strategy.md`); an attacker who can
   selectively take Redis down could replay a write past the
   idempotency guard. The underlying DB constraints (unique
   `(recurring_rule_id, scheduled_date)`, batch status transitions)
   remain the actual source of correctness for recurring transactions
   and CSV import either way, so this does not reopen the duplicate-
   transaction risk discussed in Stage 7 - it only affects the
   idempotency-key feature on `/transactions` and `/transfers`.

## 7. Dependency Vulnerabilities

| Control | Status | Evidence |
|---|---|---|
| Dependencies scanned for known CVEs | ✅ Verified | `pip-audit` (v2.10.1) run against the project's installed virtual environment on 2026-10-05: **no known vulnerabilities found** in any third-party dependency. The only skip was the local `fintrack` package itself (not published to PyPI - expected). `pip-audit` is now also a step in `.github/workflows/ci.yml`, so this check runs on every CI build going forward, not just this one-off run |

## 8. Overall Assessment

No critical or high-severity finding from this review. Admin
functionality (§2) is now built and tested, and the dependency scan
(§7) found nothing. No open security gaps remain from this session's
work; the residual risks in §6 are accepted trade-offs, not omissions.
