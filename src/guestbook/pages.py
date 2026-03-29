"""Server-rendered page routes (separate from /api/v1)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import get_db
from guestbook.config import settings
from guestbook.models.event import Event
from guestbook.models.rsvp import RSVP, GuestGroupMember
from guestbook.models.user import Role, User
from guestbook.services.auth import create_access_token
from guestbook.services.email import send_magic_link

import markdown as _markdown_lib
from markupsafe import Markup

_BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent

router = APIRouter()
templates = Jinja2Templates(directory=_BASE_DIR / "templates")


def _md_filter(text: str) -> Markup:
    """Convert markdown to HTML. Safe for use in templates."""
    html = _markdown_lib.markdown(
        text,
        extensions=["nl2br", "sane_lists", "smarty"],
    )
    return Markup(html)


templates.env.filters["markdown"] = _md_filter


async def _get_user_or_none(
    request: Request, db: AsyncSession
) -> User | None:
    """Get the current user from session, or None if not logged in.

    The user is expunged from the session to prevent lazy-load issues
    with ORM relationship backpopulation (e.g. User.rsvps).
    """
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is not None:
        db.expunge(user)
    return user


def _flash(request: Request, category: str, message: str) -> None:
    """Add a flash message to the session."""
    if "_flashes" not in request.session:
        request.session["_flashes"] = []
    request.session["_flashes"].append([category, message])


def _get_flashed_messages(request: Request) -> list[tuple[str, str]]:
    """Retrieve and clear flash messages from the session."""
    messages = request.session.pop("_flashes", [])
    return [(m[0], m[1]) for m in messages]


def _ensure_csrf_token(request: Request) -> str:
    """Ensure a CSRF token exists in the session and return it."""
    if "csrf_token" not in request.session:
        import secrets as _secrets
        request.session["csrf_token"] = _secrets.token_hex(32)
    return request.session["csrf_token"]


def _template_context(request: Request, user: User | None, **kwargs):
    """Build template context with common variables."""
    return {
        "request": request,
        "user": user,
        "csrf_token": _ensure_csrf_token(request),
        "get_flashed_messages": lambda: _get_flashed_messages(request),
        **kwargs,
    }


def _validate_csrf(request: Request, form_token: str) -> bool:
    """Validate CSRF token from form against session."""
    import secrets as _secrets
    session_token = request.session.get("csrf_token", "")
    if not session_token or not form_token:
        return False
    return _secrets.compare_digest(str(form_token), session_token)


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    result = await db.execute(
        select(Event)
        .where(Event.archived_at.is_(None))
        .order_by(Event.date.asc())
    )
    events = list(result.scalars().all())
    return templates.TemplateResponse(
        "index.html",
        _template_context(request, user, events=events),
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Show the login form. Redirect to home if already logged in."""
    user = await _get_user_or_none(request, db)
    if user is not None:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        _template_context(request, None),
    )


@router.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Send a magic login link for an existing user."""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Only send if user exists — but always show the same response
    if user is not None:
        raw_token = await create_access_token(db, user)
        verify_url = f"{settings.base_url}/api/v1/auth/verify/{raw_token}"
        send_magic_link(email, verify_url)

    return templates.TemplateResponse(
        "link_sent.html",
        _template_context(
            request, None,
            invite_code="",
            token_expiry_hours=settings.token_expiry_hours,
        ),
    )


@router.get("/e/{invite_code}", response_class=HTMLResponse)
async def event_page(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Event).where(
            Event.invite_code == invite_code,
            Event.archived_at.is_(None),
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(
                request, None,
                title="Event Not Found",
                message="This event doesn't exist or has been archived.",
            ),
            status_code=404,
        )

    user = await _get_user_or_none(request, db)
    cutoff = event.rsvp_cutoff
    if cutoff is not None and cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=UTC)
    past_cutoff = cutoff is not None and datetime.now(UTC) > cutoff

    existing_rsvp = None
    if user:
        result = await db.execute(
            select(RSVP).where(
                RSVP.user_id == user.id, RSVP.event_id == event.id
            )
        )
        existing_rsvp = result.scalar_one_or_none()

    return templates.TemplateResponse(
        "event.html",
        _template_context(
            request, user,
            event=event,
            past_cutoff=past_cutoff,
            existing_rsvp=existing_rsvp,
        ),
    )


@router.post("/e/{invite_code}/register")
async def register(
    invite_code: str,
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Handle email registration form — send magic link."""
    result = await db.execute(
        select(Event).where(
            Event.invite_code == invite_code,
            Event.archived_at.is_(None),
        )
    )
    event = result.scalar_one_or_none()

    # Always show the same response to prevent enumeration
    reg_cutoff = event.rsvp_cutoff if event else None
    if reg_cutoff is not None and reg_cutoff.tzinfo is None:
        reg_cutoff = reg_cutoff.replace(tzinfo=UTC)
    if event is None or (
        reg_cutoff and reg_cutoff < datetime.now(UTC)
    ):
        return templates.TemplateResponse(
            "link_sent.html",
            _template_context(
                request, None,
                invite_code=invite_code,
                token_expiry_hours=settings.token_expiry_hours,
            ),
        )

    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate token and send magic link
    raw_token = await create_access_token(db, user)
    verify_url = f"{settings.base_url}/api/v1/auth/verify/{raw_token}?invite_code={event.invite_code}"
    send_magic_link(email, verify_url)

    return templates.TemplateResponse(
        "link_sent.html",
        _template_context(
            request, None,
            invite_code=invite_code,
            token_expiry_hours=settings.token_expiry_hours,
        ),
    )


@router.get("/e/{invite_code}/rsvp", response_class=HTMLResponse)
async def rsvp_form(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url=f"/e/{invite_code}", status_code=303)

    result = await db.execute(
        select(Event).where(Event.invite_code == invite_code)
    )
    event = result.scalar_one_or_none()
    if event is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(
                request, user,
                title="Event Not Found",
                message="This event doesn't exist.",
            ),
            status_code=404,
        )

    form_cutoff = event.rsvp_cutoff
    if form_cutoff is not None and form_cutoff.tzinfo is None:
        form_cutoff = form_cutoff.replace(tzinfo=UTC)
    past_cutoff = form_cutoff is not None and datetime.now(UTC) > form_cutoff

    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.user_id == user.id, RSVP.event_id == event.id)
    )
    rsvp = result.scalar_one_or_none()

    return templates.TemplateResponse(
        "rsvp_form.html",
        _template_context(
            request, user,
            event=event,
            rsvp=rsvp,
            readonly=past_cutoff and user.role.value < Role.manager.value,
        ),
    )


@router.post("/e/{invite_code}/rsvp")
async def rsvp_submit(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url=f"/e/{invite_code}", status_code=303)

    result = await db.execute(
        select(Event).where(Event.invite_code == invite_code)
    )
    event = result.scalar_one_or_none()
    if event is None:
        return RedirectResponse(url="/", status_code=303)

    # Enforce cutoff for guests
    sub_cutoff = event.rsvp_cutoff
    if sub_cutoff is not None and sub_cutoff.tzinfo is None:
        sub_cutoff = sub_cutoff.replace(tzinfo=UTC)
    if (
        sub_cutoff
        and datetime.now(UTC) > sub_cutoff
        and user.role.value < Role.manager.value
    ):
        _flash(request, "error", "RSVP deadline has passed.")
        return RedirectResponse(
            url=f"/e/{invite_code}/rsvp", status_code=303
        )

    # Parse form data
    form = await request.form()
    attending_val = form.get("attending")
    attending = None
    if attending_val == "yes":
        attending = True
    elif attending_val == "no":
        attending = False

    notes = form.get("notes", "")
    names = form.getlist("member_name[]")
    food_prefs = form.getlist("member_food_preference[]")
    dietary = form.getlist("member_dietary_restrictions[]")

    # Find or create RSVP
    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.user_id == user.id, RSVP.event_id == event.id)
    )
    rsvp = result.scalar_one_or_none()

    if rsvp is None:
        rsvp = RSVP(
            user_id=user.id,
            event_id=event.id,
            attending=attending,
            notes=notes or None,
        )
        db.add(rsvp)
        await db.flush()
    else:
        rsvp.attending = attending
        rsvp.notes = notes or None
        # Bulk delete existing members — avoids lazy load
        from sqlalchemy import delete
        await db.execute(
            delete(GuestGroupMember).where(GuestGroupMember.rsvp_id == rsvp.id)
        )
        await db.flush()

    # Create members
    new_members = []
    for i, name in enumerate(names):
        if not name.strip():
            continue
        alcohol = form.get(f"member_alcohol_{i}") == "1"
        member = GuestGroupMember(
            rsvp_id=rsvp.id,
            name=name.strip(),
            food_preference=food_prefs[i] if i < len(food_prefs) and food_prefs[i] else None,
            dietary_restrictions=dietary[i] if i < len(dietary) and dietary[i] else None,
            alcohol=alcohol,
        )
        db.add(member)
        new_members.append(member)

    rsvp.total_guests = max(len(new_members), 1)

    await db.commit()

    # Reload with fresh data for confirmation page
    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members))
        .where(RSVP.id == rsvp.id)
        .execution_options(populate_existing=True)
    )
    rsvp = result.scalar_one()

    return templates.TemplateResponse(
        "rsvp_confirm.html",
        _template_context(request, user, event=event, rsvp=rsvp),
    )


@router.post("/logout")
async def logout_page(request: Request):
    """Clear session and redirect to home."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
