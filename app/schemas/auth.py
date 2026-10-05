from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas._password import validate_password_policy


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    full_name: str = Field(min_length=1, max_length=150)

    @field_validator("password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password_policy(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 scheme name, not a credential
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password_policy(value)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=1, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _password_policy(cls, value: str) -> str:
        return validate_password_policy(value)
