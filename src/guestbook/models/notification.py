import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


class NotificationLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "notification_logs"

    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(50))  # "event_update", "rsvp_confirmation"
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20))  # "sent", "failed"

    event: Mapped["Event"] = relationship()  # noqa: F821
    user: Mapped["User"] = relationship()  # noqa: F821
