import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import UserRole


class AdminUserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    is_verified: bool
    is_locked: bool
    created_at: datetime.datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserRead]
    page: int
    page_size: int
    total: int
    total_pages: int
