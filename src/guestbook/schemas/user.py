from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    site_role: int
    food_preference: str | None
    dietary_restrictions: str | None
    alcohol: bool
    household_id: UUID | None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str | None = None
    site_role: int = 1  # user


class SiteRoleUpdate(BaseModel):
    site_role: int
