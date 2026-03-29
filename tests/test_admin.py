"""Tests for user/admin management."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from guestbook.models.rsvp import RSVP
from guestbook.models.user import Role, User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _auth_as(client: AsyncClient, role: Role) -> User:
    async with test_session() as db:
        user = User(email=f"{role.name}-admin-test@test.com", role=role)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        raw_token = await create_access_token(db, user)
    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    return user


async def test_list_users_admin(client: AsyncClient):
    await _auth_as(client, Role.admin)

    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_list_users_guest_forbidden(client: AsyncClient):
    await _auth_as(client, Role.guest)

    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403


async def test_change_role(client: AsyncClient):
    await _auth_as(client, Role.admin)

    # Create a guest
    async with test_session() as db:
        guest = User(email="target@test.com", role=Role.guest)
        db.add(guest)
        await db.commit()
        await db.refresh(guest)
        guest_id = str(guest.id)

    # Promote to manager
    resp = await client.put(
        f"/api/v1/users/{guest_id}/role",
        json={"role": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == 2


async def test_manager_cannot_change_roles(client: AsyncClient):
    await _auth_as(client, Role.manager)

    async with test_session() as db:
        guest = User(email="target2@test.com", role=Role.guest)
        db.add(guest)
        await db.commit()
        await db.refresh(guest)
        guest_id = str(guest.id)

    resp = await client.put(
        f"/api/v1/users/{guest_id}/role",
        json={"role": 2},
    )
    assert resp.status_code == 403


async def test_delete_user_cascades(client: AsyncClient):
    await _auth_as(client, Role.admin)

    from datetime import datetime, timezone
    from guestbook.models.event import Event

    async with test_session() as db:
        event = Event(title="Cascade Test", date=datetime(2030, 1, 1, tzinfo=timezone.utc))
        db.add(event)
        guest = User(email="deleteme@test.com", role=Role.guest)
        db.add(guest)
        await db.commit()
        await db.refresh(event)
        await db.refresh(guest)

        rsvp = RSVP(user_id=guest.id, event_id=event.id, attending=True)
        db.add(rsvp)
        await db.commit()
        guest_id = str(guest.id)

    # Delete user
    resp = await client.delete(f"/api/v1/users/{guest_id}")
    assert resp.status_code == 204

    # RSVP should be gone
    async with test_session() as db:
        from uuid import UUID
        result = await db.execute(select(RSVP).where(RSVP.user_id == UUID(guest_id)))
        assert result.scalar_one_or_none() is None
