
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    max_open_tickets: int = Field(default=10, ge=1, le=100)


class AgentUpdate(BaseModel):
    is_online: bool | None = None
    is_available: bool | None = None
    max_open_tickets: int | None = Field(default=None, ge=1, le=100)


class AgentResponse(BaseModel):
    id: int
    user_id: int
    is_online: bool
    is_available: bool
    max_open_tickets: int

    model_config = ConfigDict(from_attributes=True)
