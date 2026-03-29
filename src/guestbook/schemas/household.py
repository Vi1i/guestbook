from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class HouseholdCreate(BaseModel):
    name: str


class HouseholdResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    invite_code: str
    created_at: datetime
    updated_at: datetime


class HouseholdMemberCreate(BaseModel):
    name: str
    food_preference: str | None = None
    dietary_restrictions: str | None = None
    alcohol: bool = False


class HouseholdMemberResponse(HouseholdMemberCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    household_id: UUID
    user_id: UUID | None
    created_at: datetime
    updated_at: datetime
