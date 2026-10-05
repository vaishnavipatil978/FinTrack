from enum import StrEnum
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINTRACK_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "FinTrack"
    environment: Environment = Environment.DEVELOPMENT
    log_level: str = "INFO"
    database_url: str
    db_pool_size: int = 10
    db_max_overflow: int = 10
    cors_origins: Annotated[list[str], NoDecode] = []

    # Auth - see docs/architecture/security-architecture.md §1.
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30
    password_reset_token_expire_minutes: int = 60
    max_failed_login_attempts: int = 5
    account_lockout_minutes: int = 15

    # Background jobs - see docs/architecture/background-jobs.md.
    redis_url: str = "redis://localhost:6379/0"
    recurring_rules_catchup_limit: int = 366  # safety valve against a runaway backfill loop

    # CSV import - see docs/architecture/background-jobs.md and UC-10.
    csv_import_max_rows: int = 5000
    csv_import_max_file_size_bytes: int = 2_000_000
    csv_import_sync_row_threshold: int = 50  # above this, confirm() processes asynchronously
    csv_import_preview_ttl_hours: int = 24

    # Redis-backed features - see docs/architecture/caching-strategy.md and
    # security-architecture.md §3. All fail open if Redis is unreachable.
    cache_enabled: bool = True
    report_cache_ttl_seconds: int = 600
    balances_cache_ttl_seconds: int = 120
    rate_limit_enabled: bool = True
    rate_limit_auth_per_minute: int = 10
    rate_limit_refresh_per_minute: int = 30
    idempotency_ttl_seconds: int = 86400

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        if self.environment is Environment.PRODUCTION:
            if "*" in self.cors_origins:
                raise ValueError("Wildcard CORS origin is not allowed in production")
            if len(self.jwt_secret_key) < 32:
                raise ValueError("jwt_secret_key must be at least 32 characters in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values come from the environment
