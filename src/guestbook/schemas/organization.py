from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OrgCreate(BaseModel):
    name: str
    slug: str


class OrgUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None


class OrgResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime


class OrgMembershipCreate(BaseModel):
    email: str
    org_role: int = 1  # viewer


class OrgMembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    org_id: UUID
    org_role: int
    created_at: datetime
    updated_at: datetime
