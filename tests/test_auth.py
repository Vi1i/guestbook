"""Tests for authentication flow."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from guestbook.models.event import Event
from guestbook.models.token import AccessToken
from guestbook.models.user import User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _create_event(invite_code: str = "TEST1234") -> Event:
    from datetime import datetime, timezone
    async with test_session() as db:
        event = Event(
            title="Test Event",
            date=datetime(2030, 1, 1, tzinfo=timezone.utc),
            invite_code=invite_code,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event


async def _create_user(email: str = "test@example.com", role: int = 1) -> tuple[User, str]:
    """Create a user and return (user, raw_token)."""
    from guestbook.models.user import Role
    async with test_session() as db:
        user = User(email=email, role=Role(role))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        raw_token = await create_access_token(db, user)
        return user, raw_token


async def test_request_link_valid_invite(client: AsyncClient):
    """Valid invite code should return 200 and create a user."""
    await _create_event()

    resp = await client.post(
        "/api/v1/auth/request-link",
        json={"email": "guest@example.com", "invite_code": "TEST1234"},
    )
    assert resp.status_code == 200

    # User should be created
    async with test_session() as db:
        result = await db.execute(select(User).where(User.email == "guest@example.com"))
        user = result.scalar_one_or_none()
        assert user is not None

        # Token should be created
        result = await db.execute(select(AccessToken).where(AccessToken.user_id == user.id))
        token = result.scalar_one_or_none()
        assert token is not None


async def test_request_link_invalid_invite(client: AsyncClient):
    """Invalid invite code still returns 200 (no enumeration)."""
    resp = await client.post(
        "/api/v1/auth/request-link",
        json={"email": "guest@example.com", "invite_code": "INVALID"},
    )
    assert resp.status_code == 200

    # No user should be created
    async with test_session() as db:
        result = await db.execute(select(User).where(User.email == "guest@example.com"))
        assert result.scalar_one_or_none() is None


async def test_verify_valid_token(client: AsyncClient):
    """Valid token should establish session and redirect."""
    await _create_event()
    _, raw_token = await _create_user()

    resp = await client.get(
        f"/api/v1/auth/verify/{raw_token}?invite_code=TEST1234",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/e/TEST1234/rsvp" in resp.headers["location"]


async def test_verify_expired_token(client: AsyncClient):
    """Used token should be rejected."""
    await _create_event()
    _, raw_token = await _create_user()

    # Use the token once
    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)

    # Second use should fail
    resp = await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    assert resp.status_code == 400


async def test_verify_invalid_token(client: AsyncClient):
    """Invalid token should return 400."""
    resp = await client.get("/api/v1/auth/verify/bogustoken", follow_redirects=False)
    assert resp.status_code == 400


async def test_logout(client: AsyncClient):
    """Logout should clear session."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
