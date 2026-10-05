# FinTrack — User Stories

Format: `US-<MODULE>-<NUMBER>`, story, acceptance criteria (Given/When/Then),
priority. Priority: **MVP** (required for a usable end-to-end product),
**P1** (important, ships shortly after MVP), **P2** (nice to have / later).

All stories are written from the USER role unless stated otherwise.

## Authentication

### US-AUTH-01 — Register (MVP)
As a new user, I want to register with my email and password, so that I can
start tracking my finances.
- Given a valid, unused email and a password meeting the policy, when I
  submit registration, then my account is created, my password is hashed
  (never stored in plaintext), and I receive a success response without any
  token yet (or with tokens, depending on whether email verification gates
  login — see NFR security).
- Given an email that's already registered, when I submit registration, then
  I receive a 409 Conflict with a clear error code, and no duplicate account
  is created.

### US-AUTH-02 — Login (MVP)
As a registered user, I want to log in with my email and password, so that I
can access my data.
- Given correct credentials, when I log in, then I receive an access token
  and a refresh token.
- Given incorrect credentials, when I log in, then I receive a 401 with a
  generic error message (no hint whether the email or password was wrong).
- Given repeated failed login attempts beyond the rate limit, when I try
  again, then I receive a 429 Too Many Requests.

### US-AUTH-03 — Refresh access token (MVP)
As a logged-in user, I want my session to stay valid without re-entering my
password, so that I have a smooth experience.
- Given a valid, unexpired refresh token, when I call refresh, then I
  receive a new access token and a new refresh token, and the old refresh
  token is invalidated.
- Given a refresh token that was already used once (rotation violation),
  when I call refresh with it again, then the entire token family is
  revoked and I must log in again.

### US-AUTH-04 — Logout (MVP)
As a logged-in user, I want to log out, so that my refresh token can no
longer be used if it's compromised.
- Given a valid refresh token, when I log out, then that token (or all my
  tokens, for "log out everywhere") is revoked and subsequent refresh
  attempts with it fail.

### US-AUTH-05 — Change password (MVP)
As a logged-in user, I want to change my password, so that I can maintain
account security.
- Given my correct current password and a new password meeting policy, when
  I submit the change, then my password is updated and (optionally) all
  existing sessions are revoked.
- Given an incorrect current password, when I submit the change, then I
  receive a 401 and my password is unchanged.

### US-AUTH-06 — Forgot / reset password (P1)
As a user who forgot their password, I want to reset it via email, so that I
can regain access without support intervention.
- Given a registered email, when I request a reset, then a single-use,
  time-limited reset token is generated and (in production) emailed to me;
  the response does not reveal whether the email exists.
- Given a valid, unexpired reset token and a new password, when I submit the
  reset, then my password is updated and the token cannot be reused.

## User Profile

### US-USER-01 — View my profile (MVP)
As a logged-in user, I want to view my profile, so that I can confirm my
account details.

### US-USER-02 — Update my profile (MVP)
As a logged-in user, I want to update my name, timezone, and default
currency, so that the app reflects my preferences.

### US-USER-03 — Cross-user isolation (MVP, security)
As a user, I want to be certain another user cannot view or edit my profile.
- Given user A is logged in, when they request user B's profile by id, then
  they receive a 403/404 (not user B's data).

## Accounts

### US-ACCT-01 — Create an account (MVP)
As a user, I want to create a financial account (e.g., "HDFC Salary
Account", type BANK, currency INR), so that I can start recording
transactions against it.

### US-ACCT-02 — List my accounts with balances (MVP)
As a user, I want to see all my active accounts and their current balances,
so that I know where my money is.

### US-ACCT-03 — Update an account (MVP)
As a user, I want to rename an account or change its display attributes, so
that my records stay accurate over time.

### US-ACCT-04 — Archive an account (MVP)
As a user, I want to archive an account I no longer use, so that it stops
appearing in my active balance view but its history is preserved.
- Given an archived account, when I list active accounts, then it is
  excluded; when I query its transaction history directly, it is still
  returned.

### US-ACCT-05 — Cannot access another user's account (MVP, security)
As a user, I want assurance that I cannot see or modify another user's
accounts under any endpoint.

## Categories

### US-CAT-01 — Use default categories (MVP)
As a new user, I want a sensible set of default categories available
immediately, so that I don't have to set up categories before recording my
first transaction.

### US-CAT-02 — Create a custom category (P1)
As a user, I want to add my own category (e.g., "Pet Care"), so that I can
organize spending the way that matches my life.

## Transactions

### US-TXN-01 — Record an expense (MVP)
As a user, I want to record an expense against an account and category, so
that my account balance and spending history reflect reality.
- Given a valid account I own, when I create an expense transaction, then
  the account balance decreases by the amount and the transaction appears
  in my history.

### US-TXN-02 — Record income (MVP)
As a user, I want to record income against an account, so that my balance
increases accordingly.

### US-TXN-03 — Edit a transaction (MVP)
As a user, I want to correct a transaction's amount/category/date after the
fact, so that my records stay accurate.
- Given I change a transaction's amount, when I save, then the owning
  account's balance is recalculated to reflect only the new amount (not
  double-applied).

### US-TXN-04 — Delete a transaction (MVP)
As a user, I want to delete a transaction I entered by mistake, so that it
no longer affects my balance or reports.

### US-TXN-05 — Filter and search transactions (MVP)
As a user, I want to filter my transactions by date range, account,
category, and type, and search by description, so that I can find specific
spending quickly.
- Given 500 transactions across 3 accounts, when I filter by account and a
  one-month date range with page size 20, then I get correctly paginated,
  correctly filtered results sorted by date descending by default.

### US-TXN-06 — Cannot access another user's transactions (MVP, security)

## Transfers

### US-XFER-01 — Transfer between my accounts (MVP)
As a user, I want to move money from one of my accounts to another (e.g.,
cash withdrawal from bank to cash wallet), so that both balances stay
accurate.
- Given two of my accounts in the same currency, when I create a transfer,
  then the source balance decreases and destination balance increases by
  the same amount, atomically.
- Given a simulated failure after debiting the source but before crediting
  the destination, when the operation is retried or inspected, then the
  system shows neither leg applied (full rollback) — never a half-applied
  transfer.

### US-XFER-02 — Blocked cross-currency transfer (MVP)
As a user, I want the system to prevent me from transferring between
accounts of different currencies, so that I don't create an inconsistent
balance.

### US-XFER-03 — View transfer history (P1)
As a user, I want to see a history of transfers separate from regular
transactions, so that I can distinguish "moving my own money" from actual
income/spending.

## Budgets

### US-BUDG-01 — Create a monthly category budget (MVP)
As a user, I want to set a ₹15,000 monthly budget for "Food", so that I can
track whether I'm overspending.

### US-BUDG-02 — See budget utilization (MVP)
As a user, I want to see how much of my Food budget I've used this month
and how much remains, computed from my actual transactions.

### US-BUDG-03 — Get notified when I overspend (P1)
As a user, I want a notification when my spending in a category exceeds its
budget, so that I can course-correct.

### US-BUDG-04 — View budget summary across categories (MVP)
As a user, I want a single view of all my budgeted categories for the
month with utilization for each.

## Financial Goals

### US-GOAL-01 — Create a goal (MVP)
As a user, I want to create a goal like "Emergency Fund, target ₹3,00,000 by
2027-12-31, starting from ₹1,25,000", so that I can track my progress.

### US-GOAL-02 — See progress and required monthly contribution (MVP)
As a user, I want to see my percentage progress, remaining amount, and how
much I need to save per month to hit my target date.

### US-GOAL-03 — Contribute to a goal (MVP)
As a user, I want to record a contribution toward a goal, so that its
current amount and progress update.

### US-GOAL-04 — Goal achieved flag (P1)
As a user, I want the goal to be clearly marked achieved once I reach the
target, so I get a sense of accomplishment and stop seeing it as "in
progress."

## Recurring Transactions

### US-RECUR-01 — Set up a recurring rent payment (MVP)
As a user, I want to define ₹25,000 rent, monthly, on the 5th, so that I
don't have to manually enter it every month.

### US-RECUR-02 — Recurring transactions process automatically (MVP)
As a user, I want due recurring transactions to appear in my transaction
history automatically on their scheduled date, without me doing anything.

### US-RECUR-03 — No duplicates on retry (MVP, reliability)
As a user, I want assurance that if the system retries processing (e.g.,
after a crash), it will never charge/record my rent twice for the same
month.

### US-RECUR-04 — Pause/resume/delete a recurring rule (P1)
As a user, I want to pause a subscription's recurring entry while I'm not
paying for it, and resume later, without losing the rule's history.

## CSV Import

### US-CSV-01 — Upload a CSV of past transactions (P1)
As a user, I want to upload my bank's exported CSV, so that I don't have to
manually re-enter months of history.

### US-CSV-02 — Preview before importing (P1)
As a user, I want to see which rows are valid and which have errors before
anything is committed, so that I can fix my file if needed.

### US-CSV-03 — Duplicate detection (P1)
As a user, I want the system to warn me if a row looks like a transaction I
already have, so that I don't end up with double entries.

### US-CSV-04 — Import report (P1)
As a user, I want a clear report of what was imported vs. skipped and why.

## Reporting

### US-RPT-01 — Monthly summary (MVP)
As a user, I want to see this month's total income, expenses, and savings
at a glance.

### US-RPT-02 — Category breakdown (MVP)
As a user, I want to see which categories I spent the most in this month.

### US-RPT-03 — Balances overview (MVP)
As a user, I want to see all my account balances and my total net worth
(sum of active account balances) in one place.

## Notifications

### US-NOTIF-01 — In-app notifications (P1)
As a user, I want to see a list of important events (budget exceeded, goal
achieved) inside the app.

### US-NOTIF-02 — Mark as read (P1)
As a user, I want to mark notifications as read so my unread count stays
meaningful.

## Audit / Transparency

### US-AUDIT-01 — View my own activity log (P2)
As a security-conscious user, I want to see a log of sensitive actions on my
account (logins, password changes, transaction edits), so that I can spot
unauthorized activity.

## Admin

### US-ADMIN-01 — Lock a user account (P2)
As an admin, I want to lock a user's account in response to a support
request or abuse report, so that I can respond to incidents without
deleting data.
