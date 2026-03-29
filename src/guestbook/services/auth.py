import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.config import settings
from guestbook.models.token import AccessToken
from guestbook.models.user import User


def generate_token() -> str:
    """Generate a cryptographically secure URL-safe token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """SHA-256 hash a raw token. Raw tokens are never stored."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_access_token(db: AsyncSession, user: User) -> str:
    """Create an access token for a user. Returns the raw token (not stored)."""
    raw_token = generate_token()
    token = AccessToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.token_expiry_hours),
    )
    db.add(token)
    await db.commit()
    return raw_token


async def verify_token(db: AsyncSession, raw_token: str) -> AccessToken | None:
    """Verify a raw token. Returns the AccessToken if valid, None otherwise.

    A token is valid if:
    - Its hash exists in the database
    - It has not expired
    - It has not already been used (single-use)
    """
    token_hash = hash_token(raw_token)
    result = await db.execute(
        select(AccessToken)
        .where(AccessToken.token_hash == token_hash)
        .where(AccessToken.expires_at > datetime.now(UTC))
        .where(AccessToken.used_at.is_(None))
    )
    access_token = result.scalar_one_or_none()
    if access_token is None:
        return None

    # Mark as used
    access_token.used_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(access_token)
    return access_token
