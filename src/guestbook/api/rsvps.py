import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import get_current_user, get_db, require_role
from guestbook.models.event import Event
from guestbook.models.rsvp import RSVP, GuestGroupMember
from guestbook.models.user import Role, User
from guestbook.schemas.rsvp import RSVPResponse, RSVPUpsert

router = APIRouter(prefix="/events/{event_id}", tags=["rsvps"])


async def _get_event_or_404(
    event_id: uuid.UUID, db: AsyncSession
) -> Event:
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


@router.get("/rsvp", response_model=RSVPResponse)
async def get_my_rsvp(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RSVP:
    """Get the current user's RSVP for this event."""
    await _get_event_or_404(event_id, db)

    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.user_id == current_user.id, RSVP.event_id == event_id)
    )
    rsvp = result.scalar_one_or_none()
    if rsvp is None:
        raise HTTPException(status_code=404, detail="RSVP not found")
    return rsvp


@router.put("/rsvp", response_model=RSVPResponse)
async def upsert_rsvp(
    event_id: uuid.UUID,
    body: RSVPUpsert,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RSVP:
    """Create or update the current user's RSVP with group members."""
    event = await _get_event_or_404(event_id, db)

    # Enforce rsvp_cutoff for guests
    cutoff = event.rsvp_cutoff
    if cutoff is not None and cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    if (
        cutoff
        and datetime.now(timezone.utc) > cutoff
        and current_user.role.value < Role.manager.value
    ):
        raise HTTPException(
            status_code=403,
            detail="RSVP deadline has passed",
        )

    # Find existing RSVP or create new one
    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.user_id == current_user.id, RSVP.event_id == event_id)
    )
    rsvp = result.scalar_one_or_none()

    if rsvp is None:
        rsvp = RSVP(
            user_id=current_user.id,
            event_id=event_id,
            attending=body.attending,
            notes=body.notes,
        )
        db.add(rsvp)
        await db.flush()  # get rsvp.id for members
    else:
        rsvp.attending = body.attending
        rsvp.notes = body.notes
        # Delete existing members via bulk query — avoids lazy load
        await db.execute(
            delete(GuestGroupMember).where(GuestGroupMember.rsvp_id == rsvp.id)
        )
        await db.flush()

    # Create new members
    new_members = []
    for m in body.members:
        member = GuestGroupMember(
            rsvp_id=rsvp.id,
            name=m.name,
            food_preference=m.food_preference,
            dietary_restrictions=m.dietary_restrictions,
            alcohol=m.alcohol,
        )
        db.add(member)
        new_members.append(member)

    # Sync total_guests with member count (minimum 1)
    rsvp.total_guests = max(len(new_members), 1)
    # Don't assign rsvp.members directly — it triggers lazy load of old value.
    # Members are linked via rsvp_id foreign key already.

    await db.commit()

    # Reload with fresh data — populate_existing ensures stale cache is overwritten
    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.id == rsvp.id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


@router.get("/rsvps", response_model=list[RSVPResponse])
async def list_rsvps(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(Role.manager)),
    db: AsyncSession = Depends(get_db),
) -> list[RSVP]:
    """List all RSVPs for an event (manager+ only)."""
    await _get_event_or_404(event_id, db)

    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.event_id == event_id)
    )
    return list(result.scalars().all())


@router.get("/rsvps/export")
async def export_rsvps(
    event_id: uuid.UUID,
    current_user: User = Depends(require_role(Role.manager)),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Export RSVPs for an event as CSV (manager+ only)."""
    event = await _get_event_or_404(event_id, db)

    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members), selectinload(RSVP.user))
        .where(RSVP.event_id == event_id)
    )
    rsvps = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "name", "rsvp_email", "attending", "food_preference",
        "dietary_restrictions", "alcohol", "notes",
    ])

    for rsvp in rsvps:
        attending_str = ""
        if rsvp.attending is True:
            attending_str = "yes"
        elif rsvp.attending is False:
            attending_str = "no"

        if rsvp.members:
            for i, m in enumerate(rsvp.members):
                writer.writerow([
                    m.name,
                    rsvp.user.email,
                    attending_str,
                    m.food_preference or "",
                    m.dietary_restrictions or "",
                    "yes" if m.alcohol else "no",
                    rsvp.notes or "" if i == 0 else "",
                ])
        else:
            writer.writerow([
                rsvp.user.display_name or rsvp.user.email,
                rsvp.user.email,
                attending_str,
                "",
                "",
                "",
                rsvp.notes or "",
            ])

    # Sanitize filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in event.title).strip()
    filename = f"{safe_title}-guests.csv" if safe_title else "guests.csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
