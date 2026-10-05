from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import CategoryType


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    type: CategoryType


class CategoryUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: CategoryType
    is_system: bool
    is_archived: bool
