
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TicketPriority = Literal["Low", "Medium", "High", "Urgent"]

TicketStatus = Literal[
    "Open",
    "Assigned",
    "In Progress",
    "Waiting on Customer",
    "Resolved",
    "Closed",
]


class TicketCreate(BaseModel):
    category_id: int = Field(gt=0)
    subject: str = Field(min_length=5, max_length=150)
    description: str = Field(min_length=10)
    priority: TicketPriority = "Medium"

    @field_validator("subject", "description")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("This field cannot be empty")

        return value



class TicketStatusUpdate(BaseModel):
    status: TicketStatus


class TicketPriorityUpdate(BaseModel):
    priority: TicketPriority


class TicketResponse(BaseModel):
    id: int
    ticket_number: str
    customer_id: int
    category_id: int
    assigned_agent_id: int | None
    subject: str
    description: str
    priority: str
    status: str
    first_response_due: datetime | None
    resolution_due: datetime | None
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    sla_breached: bool
    reopen_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TicketHistoryResponse(BaseModel):
    id: int
    ticket_id: int
    changed_by_id: int | None
    action: str
    old_value: str | None
    new_value: str | None
    details: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
