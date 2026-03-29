import uuid
from collections.abc import AsyncGenerator, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.database import async_session
from guestbook.models.user import Role, User


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Read the session cookie and return the authenticated User.

    The user is expunged from the session to prevent lazy-load issues
    with ORM relationship backpopulation in async contexts.
    """
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        # Session references a deleted user — clear it
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Expunge to prevent backref lazy loading when creating related objects
    db.expunge(user)
    return user


def require_role(minimum: Role) -> Callable:
    """Dependency factory that enforces a minimum role level."""
    async def dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role.value < minimum.value:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dependency
