
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=1999)
    is_internal_note: bool = False

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Message cannot be empty")

        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: int
    sender_id: int
    content: str
    is_internal_note: bool
    is_read: bool
    created_at: datetime


