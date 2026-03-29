"""Event CRUD API routes."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import (
    check_event_permission,
    check_org_permission,
    get_current_user,
    get_db,
    require_site_role,
)
from guestbook.database import async_session as session_factory
from guestbook.models.event import Event, EventVisibility
from guestbook.models.organization import OrgRole
from guestbook.models.user import SiteRole, User
from guestbook.schemas.event import EventCreate, EventResponse, EventUpdate
from guestbook.services.notification import diff_event_changes, notify_event_change, snapshot_event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=list[EventResponse])
async def list_events(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Event]:
    stmt = select(Event)
    if not include_archived:
        stmt = stmt.where(Event.archived_at.is_(None))

    # Site admin/support see all; others see only public + their org's events
    if current_user.site_role.value < SiteRole.support.value:
        from guestbook.models.organization import OrgMembership
        org_ids_stmt = select(OrgMembership.org_id).where(
            OrgMembership.user_id == current_user.id
        )
        stmt = stmt.where(
            (Event.visibility == EventVisibility.public)
            | Event.org_id.in_(org_ids_stmt)
        )

    stmt = stmt.order_by(Event.date.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    body: EventCreate,
    org_id: UUID = Query(..., description="Organization ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    """Create an event within an organization."""
    if not await check_org_permission(db, current_user, org_id, OrgRole.event_creator):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    event = Event(
        org_id=org_id,
        visibility=EventVisibility(body.visibility),
        **body.model_dump(exclude={"visibility"}),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: UUID,
    body: EventUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    if not await check_event_permission(db, current_user, event_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    old_values = snapshot_event(event)

    update_data = body.model_dump(exclude_unset=True)
    if "visibility" in update_data:
        update_data["visibility"] = EventVisibility(update_data["visibility"])
    for field, value in update_data.items():
        setattr(event, field, value)

    await db.commit()
    await db.refresh(event)

    if event.notify_on_change:
        changes = diff_event_changes(old_values, event)
        if changes:
            async def _send_notifications(eid: UUID, ch: dict):
                async with session_factory() as bg_db:
                    r = await bg_db.execute(select(Event).where(Event.id == eid))
                    bg_event = r.scalar_one_or_none()
                    if bg_event:
                        await notify_event_change(bg_db, bg_event, ch)
            background_tasks.add_task(_send_notifications, event.id, changes)

    return event


@router.post("/{event_id}/archive", response_model=EventResponse)
async def toggle_archive(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Event:
    if not await check_event_permission(db, current_user, event_id):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.archived_at is None:
        event.archived_at = datetime.now(timezone.utc)
    else:
        event.archived_at = None

    await db.commit()
    await db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete an event. Requires org admin+ or site admin."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    if not await check_org_permission(db, current_user, event.org_id, OrgRole.admin):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    await db.delete(event)
    await db.commit()
