import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


def _generate_invite_code() -> str:
    return uuid.uuid4().hex[:8]


class Event(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "events"

    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, default=_generate_invite_code
    )
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String(500), default="")
    location_url: Mapped[str | None] = mapped_column(String(2000))
    details_json: Mapped[dict | None] = mapped_column(JSON)
    rsvp_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_on_change: Mapped[bool] = mapped_column(default=True)

    rsvps: Mapped[list["RSVP"]] = relationship(  # noqa: F821
        back_populates="event", cascade="all, delete-orphan"
    )
