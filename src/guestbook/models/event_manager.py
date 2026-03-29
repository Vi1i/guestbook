import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


class EventManager(UUIDMixin, TimestampMixin, Base):
    """Per-event manager assignment. Grants a guest-role user manager
    permissions for a specific event without elevating their global role."""

    __tablename__ = "event_managers"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_event_manager_user_event"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))

    user: Mapped["User"] = relationship()  # noqa: F821
    event: Mapped["Event"] = relationship()  # noqa: F821
