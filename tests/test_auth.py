"""Tests for authentication flow."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from guestbook.models.event import Event
from guestbook.models.organization import OrgMembership, OrgRole, Organization
from guestbook.models.token import AccessToken
from guestbook.models.user import User
from guestbook.services.auth import create_access_token
from tests.conftest import test_session

pytestmark = pytest.mark.asyncio


async def _create_org_and_event(invite_code: str = "TEST1234") -> Event:
    from datetime import datetime, timezone
    async with test_session() as db:
        org = Organization(name="Test Org", slug="test-org")
        db.add(org)
        await db.flush()
        event = Event(
            org_id=org.id,
            title="Test Event",
            date=datetime(2030, 1, 1, tzinfo=timezone.utc),
            invite_code=invite_code,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event


async def _create_user(email: str = "test@example.com") -> tuple[User, str]:
    from guestbook.models.user import SiteRole
    async with test_session() as db:
        user = User(email=email, site_role=SiteRole.user)
        db.add(user)
        await db.commit()
        await db.refresh(user)
        raw_token = await create_access_token(db, user)
        return user, raw_token


async def test_request_link_valid_invite(client: AsyncClient):
    await _create_org_and_event()
    resp = await client.post(
        "/api/v1/auth/request-link",
        json={"email": "guest@example.com", "invite_code": "TEST1234"},
    )
    assert resp.status_code == 200
    async with test_session() as db:
        result = await db.execute(select(User).where(User.email == "guest@example.com"))
        assert result.scalar_one_or_none() is not None


async def test_request_link_invalid_invite(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/request-link",
        json={"email": "guest@example.com", "invite_code": "INVALID"},
    )
    assert resp.status_code == 200
    async with test_session() as db:
        result = await db.execute(select(User).where(User.email == "guest@example.com"))
        assert result.scalar_one_or_none() is None


async def test_verify_valid_token(client: AsyncClient):
    await _create_org_and_event()
    _, raw_token = await _create_user()
    resp = await client.get(
        f"/api/v1/auth/verify/{raw_token}?invite_code=TEST1234",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/e/TEST1234/rsvp" in resp.headers["location"]


async def test_verify_used_token(client: AsyncClient):
    await _create_org_and_event()
    _, raw_token = await _create_user()
    await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    resp = await client.get(f"/api/v1/auth/verify/{raw_token}", follow_redirects=False)
    assert resp.status_code == 400


async def test_verify_invalid_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/verify/bogustoken", follow_redirects=False)
    assert resp.status_code == 400


async def test_logout(client: AsyncClient):
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
