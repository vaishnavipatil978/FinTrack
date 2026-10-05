import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import NotificationChannel


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    message: str
    is_read: bool
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="notification_metadata")
    created_at: datetime.datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationRead]
    page: int
    page_size: int
    total: int
    total_pages: int


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    channel: NotificationChannel
    is_enabled: bool


class NotificationPreferenceUpdate(BaseModel):
    type: str
    channel: NotificationChannel
    is_enabled: bool


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="audit_metadata")
    request_id: str | None
    created_at: datetime.datetime


class AuditListResponse(BaseModel):
    items: list[AuditLogRead]
    page: int
    page_size: int
    total: int
    total_pages: int
