from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_db
from guestbook.config import settings
from guestbook.models.event import Event
from guestbook.models.user import User
from guestbook.schemas.auth import RequestLinkBody, RequestLinkResponse
from guestbook.services.auth import create_access_token, verify_token
from guestbook.services.email import send_magic_link

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/request-link", response_model=RequestLinkResponse)
@limiter.limit(settings.rate_limit_auth)
async def request_link(
    request: Request,
    body: RequestLinkBody,
    db: AsyncSession = Depends(get_db),
) -> RequestLinkResponse:
    """Request a magic login link.

    Validates the invite code against active events. If valid, creates or
    finds the user and generates a magic link. Always returns 200 to
    prevent enumeration.
    """
    # Validate invite code against an active, non-archived event
    result = await db.execute(
        select(Event).where(
            Event.invite_code == body.invite_code,
            Event.archived_at.is_(None),
        )
    )
    event = result.scalar_one_or_none()

    if event is None:
        # Invalid invite code — return 200 anyway to prevent enumeration
        return RequestLinkResponse()

    # Check RSVP cutoff
    auth_cutoff = event.rsvp_cutoff
    if auth_cutoff is not None and auth_cutoff.tzinfo is None:
        auth_cutoff = auth_cutoff.replace(tzinfo=UTC)
    if auth_cutoff and auth_cutoff < datetime.now(UTC):
        return RequestLinkResponse()

    # Find or create user
    result = await db.execute(
        select(User).where(User.email == body.email)
    )
    user = result.scalar_one_or_none()

    if user is None:
        user = User(email=body.email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate token and send magic link
    raw_token = await create_access_token(db, user)
    verify_url = f"{settings.base_url}/api/v1/auth/verify/{raw_token}?invite_code={event.invite_code}"
    send_magic_link(body.email, verify_url)

    return RequestLinkResponse()


@router.get("/verify/{token}")
async def verify(
    token: str,
    request: Request,
    invite_code: str = "",
    next: str = "",
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Verify a magic link token and establish a session."""
    access_token = await verify_token(db, token)

    if access_token is None:
        from pathlib import Path
        from fastapi.templating import Jinja2Templates
        _tmpl = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")
        return _tmpl.TemplateResponse(
            "error.html",
            {
                "request": request,
                "user": None,
                "get_flashed_messages": lambda: [],
                "title": "Link Expired",
                "message": "This link is invalid or has expired. Please request a new one.",
            },
            status_code=400,
        )

    # Load the user to get their role
    result = await db.execute(
        select(User).where(User.id == access_token.user_id)
    )
    user = result.scalar_one()

    # Set session
    request.session["user_id"] = str(user.id)
    request.session["role"] = user.role.value

    # Redirect: explicit next path > invite code RSVP > home
    if next and next.startswith("/"):
        return RedirectResponse(url=next, status_code=303)
    if invite_code:
        return RedirectResponse(url=f"/e/{invite_code}/rsvp", status_code=303)
    return RedirectResponse(url="/", status_code=303)


@router.post("/logout")
async def logout(request: Request) -> dict:
    """Clear the session cookie."""
    request.session.clear()
    return {"message": "Logged out"}
