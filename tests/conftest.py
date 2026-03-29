"""Test fixtures — async SQLite file-based, httpx AsyncClient, test app."""

import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from guestbook.models.base import Base

# Force debug mode so session cookies work over http in tests
os.environ["GUESTBOOK_DEBUG"] = "true"
os.environ["GUESTBOOK_SECRET_KEY"] = "test-secret-key"

# Use temp file for test DB so connections don't conflict
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
TEST_DB_PATH = _tmp.name

engine = create_async_engine(f"sqlite+aiosqlite:///{TEST_DB_PATH}", echo=False)
test_session = async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test and drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    """Session for test setup/assertions."""
    async with test_session() as session:
        yield session


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Create an httpx AsyncClient with per-request DB sessions from the test engine."""
    from importlib import reload
    import guestbook.config
    reload(guestbook.config)

    from guestbook.api.deps import get_db
    from guestbook.app import create_app

    app = create_app()

    async def _override_get_db():
        async with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
