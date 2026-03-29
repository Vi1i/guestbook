"""Organization page routes (server-rendered)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import check_org_permission, get_db, get_org_membership
from guestbook.config import settings
from guestbook.models.event import Event, EventVisibility
from guestbook.models.event_manager import EventManager
from guestbook.models.organization import OrgMembership, OrgRole, Organization
from guestbook.models.rsvp import RSVP
from guestbook.models.user import SiteRole, User
from guestbook.pages import _flash, _get_user_or_none, _md_filter, _template_context

_BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(prefix="/orgs")
templates = Jinja2Templates(directory=_BASE_DIR / "templates")
templates.env.filters["markdown"] = _md_filter


def _org_denied(request: Request):
    return RedirectResponse(url="/orgs", status_code=303)


# --- Org list and creation ---


@router.get("", response_class=HTMLResponse)
async def org_list(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(
        select(Organization)
        .join(OrgMembership, OrgMembership.org_id == Organization.id)
        .where(OrgMembership.user_id == user.id)
        .order_by(Organization.name)
    )
    orgs = list(result.scalars().all())

    return templates.TemplateResponse(
        "orgs/list.html",
        _template_context(request, user, orgs=orgs),
    )


@router.get("/new", response_class=HTMLResponse)
async def org_new(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(
        "orgs/new.html",
        _template_context(request, user),
    )


@router.post("/new")
async def org_create(
    request: Request,
    name: str = Form(...),
    slug: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    import re
    final_slug = slug.strip() if slug.strip() else name
    final_slug = re.sub(r"[^\w\s-]", "", final_slug.lower())
    final_slug = re.sub(r"[\s_]+", "-", final_slug).strip("-")[:255] or "org"

    result = await db.execute(select(Organization).where(Organization.slug == final_slug))
    if result.scalar_one_or_none():
        _flash(request, "error", f"Slug '{final_slug}' is already taken.")
        return RedirectResponse(url="/orgs/new", status_code=303)

    org = Organization(name=name, slug=final_slug)
    db.add(org)
    await db.flush()

    membership = OrgMembership(
        user_id=user.id,
        org_id=org.id,
        org_role=OrgRole.owner,
    )
    db.add(membership)
    await db.commit()

    _flash(request, "success", f"Organization '{name}' created.")
    return RedirectResponse(url=f"/orgs/{final_slug}", status_code=303)


# --- Org dashboard ---


@router.get("/{slug}", response_class=HTMLResponse)
async def org_dashboard(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, user, title="Not Found", message="Organization not found."),
            status_code=404,
        )

    if not await check_org_permission(db, user, org.id, OrgRole.viewer):
        return _org_denied(request)

    membership = await get_org_membership(db, user, org.id)
    user_org_role = membership.org_role if membership else None

    # Load events with RSVP counts
    result = await db.execute(
        select(Event).where(Event.org_id == org.id).order_by(Event.date.asc())
    )
    events = list(result.scalars().all())

    total_headcount = 0
    for event in events:
        result = await db.execute(select(RSVP).where(RSVP.event_id == event.id))
        rsvps = list(result.scalars().all())
        attending = [r for r in rsvps if r.attending is True]
        event._attending_count = len(attending)
        event._attending_guests = sum(r.total_guests for r in attending)
        event._declined_count = sum(1 for r in rsvps if r.attending is False)
        event._pending_count = sum(1 for r in rsvps if r.attending is None)
        total_headcount += event._attending_guests

    stats = {
        "total_events": len([e for e in events if e.archived_at is None]),
        "headcount": total_headcount,
    }

    return templates.TemplateResponse(
        "orgs/dashboard.html",
        _template_context(
            request, user,
            org=org,
            user_org_role=user_org_role,
            events=events,
            stats=stats,
        ),
    )


# --- Event management within org ---


@router.get("/{slug}/events/new", response_class=HTMLResponse)
async def org_event_new(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.event_creator):
        return _org_denied(request)

    return templates.TemplateResponse(
        "orgs/event_form.html",
        _template_context(request, user, org=org, event=None, base_url=settings.base_url),
    )


@router.post("/{slug}/events/new")
async def org_event_create(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.event_creator):
        return _org_denied(request)

    form = await request.form()

    parsed_date = datetime.fromisoformat(form.get("date", ""))
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    parsed_cutoff = None
    rsvp_cutoff = form.get("rsvp_cutoff", "")
    if rsvp_cutoff:
        parsed_cutoff = datetime.fromisoformat(rsvp_cutoff)
        if parsed_cutoff.tzinfo is None:
            parsed_cutoff = parsed_cutoff.replace(tzinfo=timezone.utc)

    # Parse details_json
    details = _parse_details_json(form)

    visibility = EventVisibility(form.get("visibility", "private"))

    event = Event(
        org_id=org.id,
        title=form.get("title", ""),
        description=form.get("description", ""),
        date=parsed_date,
        location=form.get("location", ""),
        location_url=form.get("location_url", "") or None,
        rsvp_cutoff=parsed_cutoff,
        notify_on_change=bool(form.get("notify_on_change", "")),
        visibility=visibility,
        details_json=details,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    _flash(request, "success", f"Event '{event.title}' created. Invite code: {event.invite_code}")
    return RedirectResponse(url=f"/orgs/{slug}/events/{event.id}/edit", status_code=303)


@router.get("/{slug}/events/{event_id}/edit", response_class=HTMLResponse)
async def org_event_edit(
    slug: str,
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None:
        return _org_denied(request)

    from guestbook.api.deps import check_event_permission
    if not await check_event_permission(db, user, uuid.UUID(event_id)):
        return _org_denied(request)

    result = await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
    event = result.scalar_one_or_none()
    if event is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, user, title="Not Found", message="Event not found."),
            status_code=404,
        )

    # Load event managers
    result = await db.execute(
        select(EventManager)
        .options(selectinload(EventManager.user))
        .where(EventManager.event_id == event.id)
    )
    event_managers = list(result.scalars().all())

    membership = await get_org_membership(db, user, org.id)
    user_org_role = membership.org_role if membership else None

    return templates.TemplateResponse(
        "orgs/event_form.html",
        _template_context(
            request, user,
            org=org,
            event=event,
            event_managers=event_managers,
            user_org_role=user_org_role,
            base_url=settings.base_url,
        ),
    )


@router.post("/{slug}/events/{event_id}/edit")
async def org_event_update(
    slug: str,
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    from guestbook.api.deps import check_event_permission
    if not await check_event_permission(db, user, uuid.UUID(event_id)):
        return _org_denied(request)

    result = await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
    event = result.scalar_one_or_none()
    if event is None:
        return RedirectResponse(url=f"/orgs/{slug}", status_code=303)

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
    event.visibility = EventVisibility(form.get("visibility", "private"))
    event.details_json = _parse_details_json(form)

    await db.commit()
    _flash(request, "success", "Event updated.")
    return RedirectResponse(url=f"/orgs/{slug}/events/{event_id}/edit", status_code=303)


@router.get("/{slug}/events/{event_id}/guests", response_class=HTMLResponse)
async def org_event_guests(
    slug: str,
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    from guestbook.api.deps import check_event_permission
    if not await check_event_permission(db, user, uuid.UUID(event_id), write=False):
        return _org_denied(request)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()

    result = await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
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
        "orgs/guest_list.html",
        _template_context(request, user, org=org, event=event, rsvps=rsvps, stats=stats),
    )


@router.post("/{slug}/events/{event_id}/archive")
async def org_event_archive(
    slug: str,
    event_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    from guestbook.api.deps import check_event_permission
    if not await check_event_permission(db, user, uuid.UUID(event_id)):
        return _org_denied(request)

    result = await db.execute(select(Event).where(Event.id == uuid.UUID(event_id)))
    event = result.scalar_one_or_none()
    if event:
        if event.archived_at is None:
            event.archived_at = datetime.now(timezone.utc)
        else:
            event.archived_at = None
        await db.commit()

    return RedirectResponse(url=f"/orgs/{slug}", status_code=303)


# --- Org members ---


@router.get("/{slug}/members", response_class=HTMLResponse)
async def org_members(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.admin):
        return _org_denied(request)

    result = await db.execute(
        select(OrgMembership)
        .options(selectinload(OrgMembership.user))
        .where(OrgMembership.org_id == org.id)
    )
    members = list(result.scalars().all())

    membership = await get_org_membership(db, user, org.id)
    user_org_role = membership.org_role if membership else None

    return templates.TemplateResponse(
        "orgs/members.html",
        _template_context(request, user, org=org, members=members, user_org_role=user_org_role),
    )


@router.post("/{slug}/members/add")
async def org_member_add(
    slug: str,
    request: Request,
    email: str = Form(...),
    org_role: int = Form(1),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.admin):
        return _org_denied(request)

    result = await db.execute(select(User).where(User.email == email))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", f"No user found with email '{email}'.")
        return RedirectResponse(url=f"/orgs/{slug}/members", status_code=303)

    # Check not already a member
    result = await db.execute(
        select(OrgMembership).where(
            OrgMembership.user_id == target.id,
            OrgMembership.org_id == org.id,
        )
    )
    if result.scalar_one_or_none():
        _flash(request, "error", f"{email} is already a member.")
        return RedirectResponse(url=f"/orgs/{slug}/members", status_code=303)

    # Can't add as owner
    role = OrgRole(min(org_role, OrgRole.admin.value))
    membership = OrgMembership(user_id=target.id, org_id=org.id, org_role=role)
    db.add(membership)
    await db.commit()

    _flash(request, "success", f"{email} added as {role.name}.")
    return RedirectResponse(url=f"/orgs/{slug}/members", status_code=303)


@router.post("/{slug}/members/{member_id}/role")
async def org_member_role(
    slug: str,
    member_id: str,
    request: Request,
    org_role: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.owner):
        return _org_denied(request)

    result = await db.execute(
        select(OrgMembership).where(OrgMembership.id == uuid.UUID(member_id))
    )
    membership = result.scalar_one_or_none()
    if membership:
        membership.org_role = OrgRole(org_role)
        await db.commit()

    return RedirectResponse(url=f"/orgs/{slug}/members", status_code=303)


@router.post("/{slug}/members/{member_id}/remove")
async def org_member_remove(
    slug: str,
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.admin):
        return _org_denied(request)

    result = await db.execute(
        select(OrgMembership).where(OrgMembership.id == uuid.UUID(member_id))
    )
    membership = result.scalar_one_or_none()
    if membership and membership.org_role != OrgRole.owner:
        await db.delete(membership)
        await db.commit()
        _flash(request, "success", "Member removed.")
    elif membership and membership.org_role == OrgRole.owner:
        _flash(request, "error", "Cannot remove the owner.")

    return RedirectResponse(url=f"/orgs/{slug}/members", status_code=303)


# --- Event manager assignment ---


@router.post("/{slug}/events/{event_id}/managers/add")
async def event_manager_add(
    slug: str,
    event_id: str,
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.event_creator):
        return _org_denied(request)

    result = await db.execute(select(User).where(User.email == email))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", f"No user found with email '{email}'.")
        return RedirectResponse(url=f"/orgs/{slug}/events/{event_id}/edit", status_code=303)

    result = await db.execute(
        select(EventManager).where(
            EventManager.user_id == target.id,
            EventManager.event_id == uuid.UUID(event_id),
        )
    )
    if result.scalar_one_or_none():
        _flash(request, "error", f"{email} is already an event manager.")
        return RedirectResponse(url=f"/orgs/{slug}/events/{event_id}/edit", status_code=303)

    em = EventManager(user_id=target.id, event_id=uuid.UUID(event_id))
    db.add(em)
    await db.commit()
    _flash(request, "success", f"{email} added as event manager.")
    return RedirectResponse(url=f"/orgs/{slug}/events/{event_id}/edit", status_code=303)


@router.post("/{slug}/events/{event_id}/managers/{manager_id}/remove")
async def event_manager_remove(
    slug: str,
    event_id: str,
    manager_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(select(Organization).where(Organization.slug == slug))
    org = result.scalar_one_or_none()
    if org is None or not await check_org_permission(db, user, org.id, OrgRole.event_creator):
        return _org_denied(request)

    result = await db.execute(
        select(EventManager).where(EventManager.id == uuid.UUID(manager_id))
    )
    em = result.scalar_one_or_none()
    if em:
        await db.delete(em)
        await db.commit()
        _flash(request, "success", "Event manager removed.")

    return RedirectResponse(url=f"/orgs/{slug}/events/{event_id}/edit", status_code=303)


# --- Helper ---


def _parse_details_json(form) -> dict | None:
    details = {}
    for field in ("dress_code", "parking", "bring"):
        val = form.get(field, "").strip()
        if val:
            details[field] = val

    times = form.getlist("schedule_time[]")
    activities = form.getlist("schedule_activity[]")
    schedule = [
        {"time": t.strip(), "activity": a.strip()}
        for t, a in zip(times, activities)
        if t.strip() and a.strip()
    ]
    if schedule:
        details["schedule"] = schedule

    return details or None
