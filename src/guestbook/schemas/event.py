from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventCreate(BaseModel):
    title: str
    description: str = ""
    date: datetime
    location: str = ""
    location_url: str | None = None
    details_json: dict | None = None
    rsvp_cutoff: datetime | None = None
    notify_on_change: bool = True
    visibility: str = "private"


class EventUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    date: datetime | None = None
    location: str | None = None
    location_url: str | None = None
    details_json: dict | None = None
    rsvp_cutoff: datetime | None = None
    notify_on_change: bool | None = None
    visibility: str | None = None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    invite_code: str
    title: str
    description: str
    date: datetime
    location: str
    location_url: str | None
    details_json: dict | None
    rsvp_cutoff: datetime | None
    archived_at: datetime | None
    notify_on_change: bool
    visibility: str
    created_at: datetime
    updated_at: datetime
