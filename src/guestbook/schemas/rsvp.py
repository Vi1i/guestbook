from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class GuestGroupMemberSchema(BaseModel):
    name: str
    food_preference: str | None = None
    dietary_restrictions: str | None = None
    alcohol: bool = False
    is_self: bool = False
    household_member_id: UUID | None = None


class GuestGroupMemberResponse(GuestGroupMemberSchema):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class RSVPUpsert(BaseModel):
    attending: bool | None = None
    notes: str | None = None
    members: list[GuestGroupMemberSchema] = []


class RSVPResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    event_id: UUID
    attending: bool | None
    total_guests: int
    notes: str | None
    members: list[GuestGroupMemberResponse]
    created_at: datetime
    updated_at: datetime
