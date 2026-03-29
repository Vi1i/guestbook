import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


class RSVP(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "rsvps"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", name="uq_rsvp_user_event"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    attending: Mapped[bool | None] = mapped_column(default=None)
    total_guests: Mapped[int] = mapped_column(default=1)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="rsvps")  # noqa: F821
    event: Mapped["Event"] = relationship(back_populates="rsvps")  # noqa: F821
    members: Mapped[list["GuestGroupMember"]] = relationship(
        back_populates="rsvp", cascade="all, delete-orphan"
    )


class GuestGroupMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "guest_group_members"

    rsvp_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rsvps.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    food_preference: Mapped[str | None] = mapped_column(String(100))
    dietary_restrictions: Mapped[str | None] = mapped_column(Text)
    alcohol: Mapped[bool] = mapped_column(default=False)

    rsvp: Mapped["RSVP"] = relationship(back_populates="members")
