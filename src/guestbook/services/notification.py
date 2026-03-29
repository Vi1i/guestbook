"""Event change notification service."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.config import settings
from guestbook.models.event import Event
from guestbook.models.notification import NotificationLog
from guestbook.models.rsvp import RSVP
from guestbook.services.email import send_notification_email

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)

# Fields to compare for change detection
_TRACKED_FIELDS = ["title", "description", "date", "location", "location_url", "rsvp_cutoff"]


def diff_event_changes(old_values: dict, event: Event) -> dict:
    """Compare old field values with current event, return changed fields."""
    changes = {}
    for field in _TRACKED_FIELDS:
        old_val = old_values.get(field)
        new_val = getattr(event, field)
        if old_val != new_val:
            changes[field] = (str(old_val) if old_val else "—", str(new_val) if new_val else "—")
    return changes


def snapshot_event(event: Event) -> dict:
    """Take a snapshot of tracked event fields before an update."""
    return {field: getattr(event, field) for field in _TRACKED_FIELDS}


async def notify_event_change(
    db: AsyncSession,
    event: Event,
    changes: dict,
) -> int:
    """Send notifications to attending guests about event changes.

    Returns the number of notifications sent.
    """
    if not changes:
        return 0

    # Get RSVPs where attending is True or None (not explicitly declined)
    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.user))
        .where(RSVP.event_id == event.id, RSVP.attending != False)  # noqa: E712
    )
    rsvps = list(result.scalars().all())

    if not rsvps:
        return 0

    html_body = _jinja_env.get_template("event_update.html").render(
        event=event,
        changes=changes,
        base_url=settings.base_url,
    )
    subject = f"Event Updated: {event.title}"

    sent_count = 0
    for rsvp in rsvps:
        status = "sent"
        try:
            send_notification_email(rsvp.user.email, subject, html_body)
            sent_count += 1
        except Exception:
            logger.exception("Failed to notify %s", rsvp.user.email)
            status = "failed"

        log = NotificationLog(
            event_id=event.id,
            user_id=rsvp.user.id,
            type="event_update",
            sent_at=datetime.now(UTC),
            status=status,
        )
        db.add(log)

    await db.commit()
    return sent_count
