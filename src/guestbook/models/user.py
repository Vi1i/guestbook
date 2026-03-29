import enum
import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


class SiteRole(enum.IntEnum):
    user = 1
    support = 2
    admin = 3


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    site_role: Mapped[SiteRole] = mapped_column(default=SiteRole.user)

    # Personal preferences
    food_preference: Mapped[str | None] = mapped_column(String(100))
    dietary_restrictions: Mapped[str | None] = mapped_column(Text)
    alcohol: Mapped[bool] = mapped_column(default=False)

    # Household
    household_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("households.id", ondelete="SET NULL")
    )

    tokens: Mapped[list["AccessToken"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    rsvps: Mapped[list["RSVP"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
