"""Per-event guest management API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_db, require_role
from guestbook.models.event import Event
from guestbook.models.user import Role, User
from guestbook.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/events/{event_id}/guests", tags=["guests"])


@router.post("", response_model=UserResponse, status_code=201)
async def add_guest_to_event(
    event_id: uuid.UUID,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(Role.manager)),
) -> User:
    """Pre-add a guest to an event by creating/finding their user account."""
    # Verify event exists
    result = await db.execute(select(Event).where(Event.id == event_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Find or create user
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=body.email, display_name=body.display_name)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user
