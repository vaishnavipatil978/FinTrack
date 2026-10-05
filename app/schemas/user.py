import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    default_currency: str
    timezone: str
    is_verified: bool
    created_at: datetime.datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    default_currency: str | None = Field(default=None, min_length=3, max_length=3)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
