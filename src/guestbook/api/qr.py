"""QR code API endpoint."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_db, require_role
from guestbook.config import settings
from guestbook.models.event import Event
from guestbook.models.user import Role, User
from guestbook.services.qr import generate_qr_png

router = APIRouter(prefix="/events/{event_id}", tags=["qr"])


@router.get("/qr")
async def get_qr_code(
    event_id: uuid.UUID,
    size: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_role(Role.manager)),
) -> Response:
    """Generate a QR code PNG for the event's invite link."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    url = f"{settings.base_url}/e/{event.invite_code}"
    png_bytes = generate_qr_png(url, size=size)

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{event.invite_code}-qr.png"',
        },
    )
