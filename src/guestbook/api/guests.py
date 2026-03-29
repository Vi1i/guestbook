"""Per-event guest management API routes."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import check_event_permission, get_current_user, get_db
from guestbook.models.event import Event
from guestbook.models.user import User
from guestbook.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/events/{event_id}/guests", tags=["guests"])


@router.post("", response_model=UserResponse, status_code=201)
async def add_guest_to_event(
    event_id: uuid.UUID,
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    """Pre-add a guest to an event by creating/finding their user account."""
    if not await check_event_permission(db, current_user, event_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Event).where(Event.id == event_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Event not found")

    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=body.email, display_name=body.display_name)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    return user
