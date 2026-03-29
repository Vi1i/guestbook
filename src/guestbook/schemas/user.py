from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    role: int
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str | None = None
    role: int = 1  # guest


class RoleUpdate(BaseModel):
    role: int
