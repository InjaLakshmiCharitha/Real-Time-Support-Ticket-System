
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FeedbackCreate(BaseModel):
    rating: int = Field(
        ...,
        ge=1,
        le=5,
        description="Rating must be between 1 and 5",
    )
    comment: str | None = Field(
        default=None,
        max_length=1000,
    )
    
    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        if value is not None:
            value = value.strip()
            if not value:
                return None
        return value


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    customer_id: int
    rating: int
    comment: str | None = None
    created_at: datetime
