"""SQLAlchemy ORM models. Importing this package registers every table on Base.metadata,
which alembic/env.py relies on for autogenerate - see docs/database-design.md.
"""

from app.models.account import Account
from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.budget import Budget
from app.models.category import Category
from app.models.csv_import import CsvImportBatch, CsvImportRow
from app.models.goal import Goal
from app.models.goal_contribution import GoalContribution
from app.models.notification import Notification, NotificationPreference
from app.models.password_reset_token import PasswordResetToken
from app.models.recurring_occurrence import RecurringOccurrence
from app.models.recurring_rule import RecurringRule
from app.models.refresh_token import RefreshToken
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.user import User

__all__ = [
    "Account",
    "AuditLog",
    "Base",
    "Budget",
    "Category",
    "CsvImportBatch",
    "CsvImportRow",
    "Goal",
    "GoalContribution",
    "Notification",
    "NotificationPreference",
    "PasswordResetToken",
    "RecurringOccurrence",
    "RecurringRule",
    "RefreshToken",
    "Transaction",
    "Transfer",
    "User",
]
