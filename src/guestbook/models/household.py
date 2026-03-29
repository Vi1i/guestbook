import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from guestbook.models.base import Base, TimestampMixin, UUIDMixin


def _generate_household_code() -> str:
    return uuid.uuid4().hex[:8]


class Household(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "households"

    name: Mapped[str] = mapped_column(String(255))
    invite_code: Mapped[str] = mapped_column(
        String(16), unique=True, index=True, default=_generate_household_code
    )

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household", cascade="all, delete-orphan"
    )


class HouseholdMember(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "household_members"

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    food_preference: Mapped[str | None] = mapped_column(String(100))
    dietary_restrictions: Mapped[str | None] = mapped_column(Text)
    alcohol: Mapped[bool] = mapped_column(default=False)

    household: Mapped["Household"] = relationship(back_populates="members")
