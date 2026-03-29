import enum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


class Role(enum.IntEnum):
    guest = 1
    manager = 2
    admin = 3


class User(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(default=Role.guest)

    tokens: Mapped[list["AccessToken"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    rsvps: Mapped[list["RSVP"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
