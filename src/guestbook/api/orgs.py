"""Organization API routes."""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import (
    check_org_permission,
    get_current_user,
    get_db,
    get_org_membership,
    require_site_role,
)
from guestbook.models.organization import OrgMembership, OrgRole, Organization
from guestbook.models.user import SiteRole, User
from guestbook.schemas.organization import OrgCreate, OrgResponse, OrgUpdate

router = APIRouter(prefix="/orgs", tags=["organizations"])


def _slugify(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    slug = re.sub(r"[^\w\s-]", "", name.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    return slug[:255] or "org"


@router.get("", response_model=list[OrgResponse])
async def list_orgs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[Organization]:
    """List organizations the current user belongs to."""
    if current_user.site_role.value >= SiteRole.admin.value:
        result = await db.execute(select(Organization).order_by(Organization.name))
        return list(result.scalars().all())

    result = await db.execute(
        select(Organization)
        .join(OrgMembership, OrgMembership.org_id == Organization.id)
        .where(OrgMembership.user_id == current_user.id)
        .order_by(Organization.name)
    )
    return list(result.scalars().all())


@router.post("", response_model=OrgResponse, status_code=201)
async def create_org(
    body: OrgCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    """Create a new organization. The creator becomes the owner."""
    # Check slug uniqueness
    slug = _slugify(body.slug) if body.slug else _slugify(body.name)
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="An organization with this slug already exists")

    org = Organization(name=body.name, slug=slug)
    db.add(org)
    await db.flush()

    # Creator becomes owner
    membership = OrgMembership(
        user_id=current_user.id,
        org_id=org.id,
        org_role=OrgRole.owner,
    )
    db.add(membership)
    await db.commit()
    await db.refresh(org)
    return org


@router.get("/{slug}", response_model=OrgResponse)
async def get_org(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not await check_org_permission(db, current_user, org.id, OrgRole.viewer):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return org


@router.put("/{slug}", response_model=OrgResponse)
async def update_org(
    slug: str,
    body: OrgUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Organization:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not await check_org_permission(db, current_user, org.id, OrgRole.admin):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if body.name is not None:
        org.name = body.name
    if body.slug is not None:
        new_slug = _slugify(body.slug)
        existing = await db.execute(
            select(Organization).where(Organization.slug == new_slug, Organization.id != org.id)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Slug already in use")
        org.slug = new_slug

    await db.commit()
    await db.refresh(org)
    return org


@router.delete("/{slug}", status_code=204)
async def delete_org(
    slug: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found")

    if not await check_org_permission(db, current_user, org.id, OrgRole.owner):
        raise HTTPException(status_code=403, detail="Only the owner can delete an organization")

    await db.delete(org)
    await db.commit()
