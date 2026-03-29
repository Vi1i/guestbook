"""Tests for RSVP operations."""

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.models.event import Event
from guestbook.models.rsvp import RSVP
from guestbook.models.user import Role, User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _create_event_and_auth(client: AsyncClient, cutoff=None) -> str:
    """Create event and user via direct DB, auth the client. Returns event_id."""
    async with test_session() as db:
        event = Event(
            title="Test Event",
            date=datetime(2030, 6, 1, tzinfo=timezone.utc),
            invite_code="RSVPTEST",
            rsvp_cutoff=cutoff,
        )
        db.add(event)
        user = User(email="rsvpguest@test.com", role=Role.guest)
        db.add(user)
        await db.commit()
        await db.refresh(event)
        await db.refresh(user)

        raw_token = await create_access_token(db, user)
        event_id = str(event.id)

    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    return event_id


async def test_upsert_rsvp(client: AsyncClient):
    event_id = await _create_event_and_auth(client)

    resp = await client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={
            "attending": True,
            "notes": "Excited!",
            "members": [
                {"name": "Alice", "food_preference": "vegetarian"},
                {"name": "Bob"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["attending"] is True
    assert data["total_guests"] == 2
    assert len(data["members"]) == 2


async def test_update_rsvp_replaces_members(client: AsyncClient):
    event_id = await _create_event_and_auth(client)

    # Create initial RSVP
    await client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"attending": True, "members": [{"name": "Alice"}]},
    )

    # Update with different members
    resp = await client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"attending": True, "members": [{"name": "Charlie"}, {"name": "Dave"}]},
    )
    data = resp.json()
    assert data["total_guests"] == 2
    names = [m["name"] for m in data["members"]]
    assert "Charlie" in names
    assert "Alice" not in names


async def test_rsvp_cutoff_enforcement(client: AsyncClient):
    """Guests can't RSVP after the cutoff."""
    event_id = await _create_event_and_auth(
        client,
        cutoff=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )

    resp = await client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"attending": True, "members": [{"name": "Late"}]},
    )
    assert resp.status_code == 403


async def test_rsvp_isolation(client: AsyncClient):
    """User A can't see User B's RSVP."""
    async with test_session() as db:
        event = Event(
            title="Isolation Test",
            date=datetime(2030, 6, 1, tzinfo=timezone.utc),
        )
        db.add(event)
        user_a = User(email="a@test.com", role=Role.guest)
        user_b = User(email="b@test.com", role=Role.guest)
        db.add(user_a)
        db.add(user_b)
        await db.commit()
        await db.refresh(event)
        await db.refresh(user_a)
        await db.refresh(user_b)

        token_a = await create_access_token(db, user_a)
        token_b = await create_access_token(db, user_b)
        event_id = str(event.id)

    # Auth as user A and create RSVP
    await client.get(f"/api/v1/auth/verify/{token_a}", follow_redirects=False)
    await client.put(
        f"/api/v1/events/{event_id}/rsvp",
        json={"attending": True, "members": [{"name": "A"}]},
    )

    # Auth as user B — should not see A's RSVP
    await client.get(f"/api/v1/auth/verify/{token_b}", follow_redirects=False)
    resp = await client.get(f"/api/v1/events/{event_id}/rsvp")
    assert resp.status_code == 404
