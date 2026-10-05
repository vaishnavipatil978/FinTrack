from enum import StrEnum


class UserRole(StrEnum):
    USER = "USER"
    ADMIN = "ADMIN"


class AccountType(StrEnum):
    BANK = "BANK"
    CASH = "CASH"
    CREDIT_CARD = "CREDIT_CARD"
    SAVINGS = "SAVINGS"
    INVESTMENT = "INVESTMENT"
    WALLET = "WALLET"


class CategoryType(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"


class TransactionType(StrEnum):
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class RecurringFrequency(StrEnum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


class RecurringStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class GoalStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACHIEVED = "ACHIEVED"
    CLOSED = "CLOSED"


class CsvBatchStatus(StrEnum):
    PENDING_PREVIEW = "PENDING_PREVIEW"
    CONFIRMED = "CONFIRMED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CsvRowStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    DUPLICATE = "DUPLICATE"
    IMPORTED = "IMPORTED"
    SKIPPED = "SKIPPED"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
