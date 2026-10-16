
from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = None
    is_active: bool | None = None


class CategoryResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SLAPolicyUpdate(BaseModel):
    first_response_minutes: int = Field(gt=0)
    resolution_minutes: int = Field(gt=0)


class SLAPolicyResponse(BaseModel):
    id: int
    priority: str
    first_response_minutes: int
    resolution_minutes: int

    model_config = ConfigDict(from_attributes=True)
