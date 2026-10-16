
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    id: int
    user_id: int
    ticket_id: int | None = None
    title: str
    message: str
    notification_type: str
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationReadResponse(BaseModel):
    detail: str
