"""Tests for event CRUD and RBAC."""

import pytest
from httpx import AsyncClient

from guestbook.models.event import Event
from guestbook.models.user import Role, User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _auth_as(client: AsyncClient, role: Role = Role.admin) -> User:
    """Create a user with the given role and authenticate the client."""
    async with test_session() as db:
        user = User(email=f"{role.name}@test.com", role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        raw_token = await create_access_token(db, user)
    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    return user


async def test_create_event_as_admin(client: AsyncClient):
    await _auth_as(client, Role.admin)

    resp = await client.post("/api/v1/events", json={
        "title": "Party",
        "date": "2030-07-04T18:00:00Z",
        "location": "Home",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Party"
    assert data["invite_code"]


async def test_create_event_as_guest_forbidden(client: AsyncClient):
    await _auth_as(client, Role.guest)

    resp = await client.post("/api/v1/events", json={
        "title": "Party",
        "date": "2030-07-04T18:00:00Z",
    })
    assert resp.status_code == 403


async def test_list_events(client: AsyncClient):
    await _auth_as(client, Role.guest)

    from datetime import datetime, timezone
    async with test_session() as db:
        event = Event(title="Visible", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        await db.commit()

    resp = await client.get("/api/v1/events")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_archive_unarchive(client: AsyncClient):
    await _auth_as(client, Role.manager)

    from datetime import datetime, timezone
    async with test_session() as db:
        event = Event(title="Archivable", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        await db.commit()
        await db.refresh(event)
        event_id = str(event.id)

    # Archive
    resp = await client.post(f"/api/v1/events/{event_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is not None

    # Unarchive
    resp = await client.post(f"/api/v1/events/{event_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["archived_at"] is None


async def test_delete_event_admin_only(client: AsyncClient):
    await _auth_as(client, Role.manager)

    from datetime import datetime, timezone
    async with test_session() as db:
        event = Event(title="Deletable", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        await db.commit()
        await db.refresh(event)
        event_id = str(event.id)

    # Manager can't delete
    resp = await client.delete(f"/api/v1/events/{event_id}")
    assert resp.status_code == 403
