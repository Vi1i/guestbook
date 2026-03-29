"""Tests for event CRUD and RBAC."""

import pytest
from httpx import AsyncClient

from guestbook.models.event import Event
from guestbook.models.organization import OrgMembership, OrgRole, Organization
from guestbook.models.user import SiteRole, User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _setup_org_and_auth(client: AsyncClient, site_role=SiteRole.user, org_role=OrgRole.owner):
    """Create org, user with membership, auth the client. Returns (org, user)."""
    async with test_session() as db:
        org = Organization(name="Test Org", slug="test-events-org")
        db.add(org)
        await db.flush()

        user = User(email=f"{site_role.name}-{org_role.name}@test.com", site_role=site_role)
        db.add(user)
        await db.flush()

        membership = OrgMembership(user_id=user.id, org_id=org.id, org_role=org_role)
        db.add(membership)
        await db.commit()
        await db.refresh(org)
        await db.refresh(user)

        raw_token = await create_access_token(db, user)
        org_id = str(org.id)

    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    return org_id


async def test_create_event_as_org_member(client: AsyncClient):
    org_id = await _setup_org_and_auth(client, org_role=OrgRole.event_creator)
    resp = await client.post(f"/api/v1/events?org_id={org_id}", json={
        "title": "Party",
        "date": "2030-07-04T18:00:00Z",
    })
    assert resp.status_code == 201
    assert resp.json()["title"] == "Party"


async def test_create_event_as_viewer_forbidden(client: AsyncClient):
    org_id = await _setup_org_and_auth(client, org_role=OrgRole.viewer)
    resp = await client.post(f"/api/v1/events?org_id={org_id}", json={
        "title": "Party",
        "date": "2030-07-04T18:00:00Z",
    })
    assert resp.status_code == 403


async def test_list_events(client: AsyncClient):
    org_id = await _setup_org_and_auth(client, org_role=OrgRole.viewer)
    from datetime import datetime, timezone
    from uuid import UUID
    async with test_session() as db:
        event = Event(org_id=UUID(org_id), title="Visible", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        await db.commit()

    resp = await client.get("/api/v1/events")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_delete_event_requires_org_admin(client: AsyncClient):
    org_id = await _setup_org_and_auth(client, org_role=OrgRole.event_creator)
    from datetime import datetime, timezone
    from uuid import UUID
    async with test_session() as db:
        event = Event(org_id=UUID(org_id), title="Deletable", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        await db.commit()
        await db.refresh(event)
        event_id = str(event.id)

    # event_creator can't delete
    resp = await client.delete(f"/api/v1/events/{event_id}")
    assert resp.status_code == 403
