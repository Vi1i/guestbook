"""FastAPI dependencies for auth and permission checks."""

import uuid
from collections.abc import AsyncGenerator, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.database import async_session
from guestbook.models.event import Event
from guestbook.models.event_manager import EventManager
from guestbook.models.organization import OrgMembership, OrgRole
from guestbook.models.user import SiteRole, User


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
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not authenticated")

    db.expunge(user)
    return user


def require_site_role(minimum: SiteRole) -> Callable:
    """Dependency factory that enforces a minimum site role level."""
    async def dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.site_role.value < minimum.value:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return dependency


async def get_org_membership(
    db: AsyncSession, user: User, org_id: uuid.UUID
) -> OrgMembership | None:
    """Get a user's membership in an organization."""
    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == user.id,
            OrgMembership.org_id == org_id,
        )
    )
    return result.scalar_one_or_none()


async def get_org_membership_by_slug(
    db: AsyncSession, user: User, slug: str
) -> OrgMembership | None:
    """Get a user's membership in an organization by slug."""
    from guestbook.models.organization import Organization
    result = await db.execute(
        select(OrgMembership)
        .join(Organization, Organization.id == OrgMembership.org_id)
        .where(
            OrgMembership.user_id == user.id,
            Organization.slug == slug,
        )
    )
    return result.scalar_one_or_none()


async def check_org_permission(
    db: AsyncSession, user: User, org_id: uuid.UUID, minimum: OrgRole
) -> bool:
    """Check if user has at least the given org role.

    Site admins always pass. Site support passes for viewer-level checks.
    """
    if user.site_role.value >= SiteRole.admin.value:
        return True
    if user.site_role.value >= SiteRole.support.value and minimum.value <= OrgRole.viewer.value:
        return True

    membership = await get_org_membership(db, user, org_id)
    if membership is None:
        return False
    return membership.org_role.value >= minimum.value


async def is_event_manager(
    db: AsyncSession, user: User, event_id: uuid.UUID
) -> bool:
    """Check if a user is an assigned manager for a specific event."""
    result = await db.execute(
        select(EventManager).where(
            EventManager.user_id == user.id,
            EventManager.event_id == event_id,
        )
    )
    return result.scalar_one_or_none() is not None


async def check_event_permission(
    db: AsyncSession, user: User, event_id: uuid.UUID, *, write: bool = True
) -> bool:
    """Check if user has manager-level access to an event.

    Checks in order: site role → org role → event manager assignment.
    Set write=False for read-only checks (support + org viewers pass).
    """
    # Site admin: full access
    if user.site_role.value >= SiteRole.admin.value:
        return True
    # Site support: read-only access
    if user.site_role.value >= SiteRole.support.value and not write:
        return True

    # Load the event to get org_id
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        return False

    # Check org membership
    membership = await get_org_membership(db, user, event.org_id)
    if membership is not None:
        if membership.org_role.value >= OrgRole.admin.value:
            return True
        if membership.org_role.value >= OrgRole.event_creator.value:
            # Event creators can manage events (we allow for now; could restrict to "own" events later)
            return True
        if membership.org_role.value >= OrgRole.viewer.value and not write:
            return True

    # Check event manager assignment
    return await is_event_manager(db, user, event_id)
