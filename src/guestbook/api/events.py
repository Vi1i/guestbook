from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_current_user, get_db, require_role
from guestbook.database import async_session as session_factory
from guestbook.models.event import Event
from guestbook.models.user import Role, User
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
    if not include_archived or current_user.role.value < Role.manager.value:
        stmt = stmt.where(Event.archived_at.is_(None))
    stmt = stmt.order_by(Event.date.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> Event:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.post("", response_model=EventResponse, status_code=201)
async def create_event(
    body: EventCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(Role.admin)),
) -> Event:
    event = Event(**body.model_dump())
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
    _current_user: User = Depends(require_role(Role.manager)),
) -> Event:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Snapshot before update for change detection
    old_values = snapshot_event(event)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)

    await db.commit()
    await db.refresh(event)

    # Trigger notifications in background if enabled
    if event.notify_on_change:
        changes = diff_event_changes(old_values, event)
        if changes:
            async def _send_notifications(event_id: UUID, changes: dict):
                async with session_factory() as bg_db:
                    result = await bg_db.execute(select(Event).where(Event.id == event_id))
                    bg_event = result.scalar_one_or_none()
                    if bg_event:
                        await notify_event_change(bg_db, bg_event, changes)

            background_tasks.add_task(_send_notifications, event.id, changes)

    return event


@router.post("/{event_id}/archive", response_model=EventResponse)
async def toggle_archive(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(Role.manager)),
) -> Event:
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
    _current_user: User = Depends(require_role(Role.admin)),
) -> None:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    await db.delete(event)
    await db.commit()
