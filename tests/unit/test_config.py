import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings

DB_URL = "postgresql+asyncpg://u:p@localhost/db"
JWT_SECRET = "unit-test-secret-key-0123456789abcdef0123456789"


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINTRACK_DATABASE_URL", DB_URL)
    monkeypatch.setenv("FINTRACK_JWT_SECRET_KEY", JWT_SECRET)
    monkeypatch.setenv("FINTRACK_CORS_ORIGINS", "http://a.example, http://b.example")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://a.example", "http://b.example"]


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINTRACK_JWT_SECRET_KEY", JWT_SECRET)
    monkeypatch.delenv("FINTRACK_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_jwt_secret_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FINTRACK_DATABASE_URL", DB_URL)
    monkeypatch.delenv("FINTRACK_JWT_SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_wildcard_cors_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        Settings(
            environment=Environment.PRODUCTION,
            database_url=DB_URL,
            jwt_secret_key=JWT_SECRET,
            cors_origins=["*"],
        )


def test_short_jwt_secret_key_rejected_in_production() -> None:
    with pytest.raises(ValidationError, match="jwt_secret_key must be at least 32"):
        Settings(
            environment=Environment.PRODUCTION,
            database_url=DB_URL,
            jwt_secret_key="too-short",
        )


def test_short_jwt_secret_key_allowed_outside_production() -> None:
    settings = Settings(
        environment=Environment.DEVELOPMENT, database_url=DB_URL, jwt_secret_key="short"
    )

    assert settings.jwt_secret_key == "short"


def test_log_level_is_normalised() -> None:
    settings = Settings(database_url=DB_URL, jwt_secret_key=JWT_SECRET, log_level="debug")

    assert settings.log_level == "DEBUG"
