"""Tests for site admin user management."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from guestbook.models.rsvp import RSVP
from guestbook.models.user import SiteRole, User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _auth_as(client: AsyncClient, site_role: SiteRole) -> User:
    async with test_session() as db:
        user = User(email=f"{site_role.name}-admin-test@test.com", site_role=site_role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        raw_token = await create_access_token(db, user)
    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    return user


async def test_list_users_admin(client: AsyncClient):
    await _auth_as(client, SiteRole.admin)
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_list_users_regular_forbidden(client: AsyncClient):
    await _auth_as(client, SiteRole.user)
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403


async def test_change_site_role(client: AsyncClient):
    await _auth_as(client, SiteRole.admin)
    async with test_session() as db:
        target = User(email="target@test.com", site_role=SiteRole.user)
        db.add(target)
        await db.commit()
        await db.refresh(target)
        target_id = str(target.id)

    resp = await client.put(
        f"/api/v1/users/{target_id}/role",
        json={"site_role": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["site_role"] == 2


async def test_support_cannot_change_roles(client: AsyncClient):
    await _auth_as(client, SiteRole.support)
    async with test_session() as db:
        target = User(email="target2@test.com", site_role=SiteRole.user)
        db.add(target)
        await db.commit()
        await db.refresh(target)
        target_id = str(target.id)

    resp = await client.put(
        f"/api/v1/users/{target_id}/role",
        json={"site_role": 2},
    )
    assert resp.status_code == 403


async def test_delete_user_cascades(client: AsyncClient):
    await _auth_as(client, SiteRole.admin)
    from datetime import datetime, timezone
    from guestbook.models.event import Event
    from guestbook.models.organization import Organization

    async with test_session() as db:
        org = Organization(name="Del Org", slug="del-org")
        db.add(org)
        await db.flush()
        event = Event(org_id=org.id, title="Cascade Test", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        guest = User(email="deleteme@test.com", site_role=SiteRole.user)
        db.add(guest)
        await db.commit()
        await db.refresh(event)
        await db.refresh(guest)
        rsvp = RSVP(user_id=guest.id, event_id=event.id, attending=True)
        db.add(rsvp)
        await db.commit()
        guest_id = str(guest.id)

    resp = await client.delete(f"/api/v1/users/{guest_id}")
    assert resp.status_code == 204

    async with test_session() as db:
        from uuid import UUID
        result = await db.execute(select(RSVP).where(RSVP.user_id == UUID(guest_id)))
        assert result.scalar_one_or_none() is None
