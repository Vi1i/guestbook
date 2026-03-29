"""Admin page routes (server-rendered)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import get_db
from guestbook.config import settings
from guestbook.models.event import Event
from guestbook.models.rsvp import RSVP
from guestbook.models.user import Role, User
from guestbook.pages import _flash, _get_user_or_none, _template_context
from guestbook.services.auth import create_access_token
from guestbook.services.email import send_magic_link

_BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=_BASE_DIR / "templates")

# Share the markdown filter with admin templates
from guestbook.pages import _md_filter
templates.env.filters["markdown"] = _md_filter


class _NotAuthorized:
    """Sentinel indicating the user is not authorized (not logged in or wrong role)."""
    def __init__(self, logged_in: bool):
        self.logged_in = logged_in


async def _require_manager(request: Request, db: AsyncSession) -> User | _NotAuthorized:
    """Return user if manager+, else a sentinel."""
    user = await _get_user_or_none(request, db)
    if user is None:
        return _NotAuthorized(logged_in=False)
    if user.role.value < Role.manager.value:
        return _NotAuthorized(logged_in=True)
    return user


async def _require_admin(request: Request, db: AsyncSession) -> User | _NotAuthorized:
    """Return user if admin, else a sentinel."""
    user = await _get_user_or_none(request, db)
    if user is None:
        return _NotAuthorized(logged_in=False)
    if user.role.value < Role.admin.value:
        return _NotAuthorized(logged_in=True)
    return user


def _deny(request: Request, result: _NotAuthorized):
    """Redirect to login if not authenticated, show 403 if wrong role."""
    if not result.logged_in:
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        "error.html",
        _template_context(request, None, title="Forbidden", message="You don't have permission to access this page."),
        status_code=403,
    )


@router.get("/login", response_class=HTMLResponse)
async def admin_login(request: Request, db: AsyncSession = Depends(get_db)):
    """Show the admin login form. If already logged in as manager+, redirect to dashboard."""
    user = await _get_user_or_none(request, db)
    if user is not None and user.role.value >= Role.manager.value:
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(
        "admin/login.html",
        _template_context(request, user),
    )


@router.post("/login")
async def admin_login_submit(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Send a magic login link for admin access (no invite code required)."""
    # Find existing user — don't create new ones via admin login
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Always show same response to prevent enumeration
    if user is not None and user.role.value >= Role.manager.value:
        raw_token = await create_access_token(db, user)
        verify_url = f"{settings.base_url}/api/v1/auth/verify/{raw_token}?next=/admin"
        send_magic_link(email, verify_url)

    _flash(request, "success", "If that email belongs to an admin account, a login link has been sent.")
    return templates.TemplateResponse(
        "admin/login.html",
        _template_context(request, None),
    )


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    # Get active events with RSVP counts
    result = await db.execute(
        select(Event).order_by(Event.date.asc())
    )
    events = list(result.scalars().all())

    total_attending = 0
    total_declined = 0
    total_pending = 0
    total_headcount = 0

    for event in events:
        result = await db.execute(
            select(RSVP).where(RSVP.event_id == event.id)
        )
        rsvps = list(result.scalars().all())
        attending_rsvps = [r for r in rsvps if r.attending is True]
        event._attending_count = len(attending_rsvps)
        event._attending_guests = sum(r.total_guests for r in attending_rsvps)
        event._declined_count = sum(1 for r in rsvps if r.attending is False)
        event._pending_count = sum(1 for r in rsvps if r.attending is None)
        total_attending += event._attending_count
        total_declined += event._declined_count
        total_pending += event._pending_count
        total_headcount += event._attending_guests

    active_count = sum(1 for e in events if e.archived_at is None)

    stats = {
        "total_events": active_count,
        "total_rsvps": total_attending + total_declined + total_pending,
        "attending": total_attending,
        "headcount": total_headcount,
        "declined": total_declined,
    }

    return templates.TemplateResponse(
        "admin/dashboard.html",
        _template_context(request, user, events=events, stats=stats),
    )


@router.get("/events", response_class=HTMLResponse)
async def event_list(
    request: Request,
    show_archived: int = 0,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    stmt = select(Event).order_by(Event.date.desc())
    if not show_archived:
        stmt = stmt.where(Event.archived_at.is_(None))
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    for event in events:
        result = await db.execute(
            select(func.count()).select_from(RSVP).where(RSVP.event_id == event.id)
        )
        event._rsvp_count = result.scalar()

    return templates.TemplateResponse(
        "admin/event_list.html",
        _template_context(request, user, events=events, show_archived=bool(show_archived)),
    )


@router.get("/events/new", response_class=HTMLResponse)
async def event_new(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    return templates.TemplateResponse(
        "admin/event_form.html",
        _template_context(request, user, event=None, base_url=settings.base_url),
    )


def _parse_details_json(form) -> dict | None:
    """Build details_json from form fields."""
    details = {}

    dress_code = form.get("dress_code", "").strip()
    if dress_code:
        details["dress_code"] = dress_code

    parking = form.get("parking", "").strip()
    if parking:
        details["parking"] = parking

    bring = form.get("bring", "").strip()
    if bring:
        details["bring"] = bring

    # Schedule
    times = form.getlist("schedule_time[]")
    activities = form.getlist("schedule_activity[]")
    schedule = []
    for t, a in zip(times, activities):
        if t.strip() and a.strip():
            schedule.append({"time": t.strip(), "activity": a.strip()})
    if schedule:
        details["schedule"] = schedule

    return details or None


@router.post("/events/new", response_class=HTMLResponse)
async def event_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_admin(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    form = await request.form()
    title = form.get("title", "")
    description = form.get("description", "")
    date = form.get("date", "")
    location = form.get("location", "")
    location_url = form.get("location_url", "")
    rsvp_cutoff = form.get("rsvp_cutoff", "")
    notify_on_change = form.get("notify_on_change", "")

    parsed_date = datetime.fromisoformat(date)
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    parsed_cutoff = None
    if rsvp_cutoff:
        parsed_cutoff = datetime.fromisoformat(rsvp_cutoff)
        if parsed_cutoff.tzinfo is None:
            parsed_cutoff = parsed_cutoff.replace(tzinfo=timezone.utc)

    event = Event(
        title=title,
        description=description,
        date=parsed_date,
        location=location,
        location_url=location_url or None,
        rsvp_cutoff=parsed_cutoff,
        notify_on_change=bool(notify_on_change),
        details_json=_parse_details_json(form),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    _flash(request, "success", f"Event '{event.title}' created. Invite code: {event.invite_code}")
    return RedirectResponse(url=f"/admin/events/{event.id}/edit", status_code=303)


@router.get("/events/{event_id}/edit", response_class=HTMLResponse)
async def event_edit(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    result = await db.execute(
        select(Event).where(Event.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, user, title="Not Found", message="Event not found."),
            status_code=404,
        )

    return templates.TemplateResponse(
        "admin/event_form.html",
        _template_context(request, user, event=event, base_url=settings.base_url),
    )


@router.post("/events/{event_id}/edit")
async def event_update(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    result = await db.execute(
        select(Event).where(Event.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return RedirectResponse(url="/admin/events", status_code=303)

    form = await request.form()
    date = form.get("date", "")
    rsvp_cutoff = form.get("rsvp_cutoff", "")

    parsed_date = datetime.fromisoformat(date)
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    parsed_cutoff = None
    if rsvp_cutoff:
        parsed_cutoff = datetime.fromisoformat(rsvp_cutoff)
        if parsed_cutoff.tzinfo is None:
            parsed_cutoff = parsed_cutoff.replace(tzinfo=timezone.utc)

    event.title = form.get("title", "")
    event.description = form.get("description", "")
    event.date = parsed_date
    event.location = form.get("location", "")
    event.location_url = form.get("location_url", "") or None
    event.rsvp_cutoff = parsed_cutoff
    event.notify_on_change = bool(form.get("notify_on_change", ""))
    event.details_json = _parse_details_json(form)

    await db.commit()
    _flash(request, "success", "Event updated.")
    return RedirectResponse(url=f"/admin/events/{event_id}/edit", status_code=303)


@router.post("/events/{event_id}/archive")
async def event_archive(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    result = await db.execute(
        select(Event).where(Event.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return RedirectResponse(url="/admin/events", status_code=303)

    if event.archived_at is None:
        event.archived_at = datetime.now(timezone.utc)
        _flash(request, "success", f"'{event.title}' archived.")
    else:
        event.archived_at = None
        _flash(request, "success", f"'{event.title}' unarchived.")

    await db.commit()
    return RedirectResponse(url="/admin/events", status_code=303)


@router.get("/events/{event_id}/guests", response_class=HTMLResponse)
async def guest_list(
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _require_manager(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    result = await db.execute(
        select(Event).where(Event.id == uuid.UUID(event_id))
    )
    event = result.scalar_one_or_none()
    if event is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, user, title="Not Found", message="Event not found."),
            status_code=404,
        )

    result = await db.execute(
        select(RSVP)
        .options(selectinload(RSVP.members), selectinload(RSVP.user))
        .where(RSVP.event_id == event.id)
    )
    rsvps = list(result.scalars().all())

    stats = {
        "attending": sum(1 for r in rsvps if r.attending is True),
        "declined": sum(1 for r in rsvps if r.attending is False),
        "pending": sum(1 for r in rsvps if r.attending is None),
        "total_guests": sum(r.total_guests for r in rsvps if r.attending is True),
    }

    return templates.TemplateResponse(
        "admin/guest_list.html",
        _template_context(request, user, event=event, rsvps=rsvps, stats=stats),
    )


# --- User Management ---


@router.get("/users", response_class=HTMLResponse)
async def user_list(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _require_admin(request, db)
    if isinstance(user, _NotAuthorized):
        return _deny(request, user)

    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = list(result.scalars().all())

    return templates.TemplateResponse(
        "admin/user_list.html",
        _template_context(request, user, users=users),
    )


@router.post("/users/{user_id}/role")
async def user_role_change(
    user_id: str,
    request: Request,
    role: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(request, db)
    if admin is None:
        return _forbidden(request)

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/admin/users", status_code=303)

    target.role = Role(role)
    await db.commit()
    _flash(request, "success", f"Role for {target.email} updated to {target.role.name}.")
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def user_delete(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _require_admin(request, db)
    if admin is None:
        return _forbidden(request)

    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/admin/users", status_code=303)

    email = target.email
    await db.delete(target)
    await db.commit()
    _flash(request, "success", f"User {email} deleted.")
    return RedirectResponse(url="/admin/users", status_code=303)
