"""Server-rendered page routes (separate from /api/v1)."""

import uuid
from datetime import UTC, datetime

import markdown as _markdown_lib
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import get_db
from guestbook.config import settings
from guestbook.models.event import Event, EventVisibility
from guestbook.models.event_manager import EventManager
from guestbook.models.household import Household, HouseholdMember
from guestbook.models.organization import OrgMembership
from guestbook.models.rsvp import RSVP, GuestGroupMember
from guestbook.models.user import SiteRole, User
from guestbook.services.auth import create_access_token
from guestbook.services.email import send_magic_link

_BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent

router = APIRouter()
templates = Jinja2Templates(directory=_BASE_DIR / "templates")


def _md_filter(text: str) -> Markup:
    """Convert markdown to HTML."""
    html = _markdown_lib.markdown(text, extensions=["nl2br", "sane_lists", "smarty"])
    return Markup(html)


def _plain_preview(text: str, length: int = 150) -> str:
    """Convert markdown to plain text and truncate for previews."""
    import re
    plain = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    plain = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', plain)
    plain = re.sub(r'[*_~`#>]+', '', plain)
    plain = re.sub(r'\n+', ' ', plain).strip()
    if len(plain) > length:
        return plain[:length].rsplit(' ', 1)[0] + '...'
    return plain


templates.env.filters["markdown"] = _md_filter
templates.env.filters["plain_preview"] = _plain_preview


async def _get_user_or_none(
    request: Request, db: AsyncSession
) -> User | None:
    """Get the current user from session, or None if not logged in."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is not None:
        # Check management access for nav bar
        has_mgmt = False
        if user.site_role.value >= SiteRole.support.value:
            has_mgmt = True
        else:
            # Check org memberships
            result = await db.execute(
                select(OrgMembership).where(OrgMembership.user_id == user.id).limit(1)
            )
            if result.scalar_one_or_none() is not None:
                has_mgmt = True
            else:
                # Check event manager assignments
                result = await db.execute(
                    select(EventManager).where(EventManager.user_id == user.id).limit(1)
                )
                if result.scalar_one_or_none() is not None:
                    has_mgmt = True
        request.state.has_management_access = has_mgmt
        db.expunge(user)
    return user


def _flash(request: Request, category: str, message: str) -> None:
    if "_flashes" not in request.session:
        request.session["_flashes"] = []
    request.session["_flashes"].append([category, message])


def _get_flashed_messages(request: Request) -> list[tuple[str, str]]:
    messages = request.session.pop("_flashes", [])
    return [(m[0], m[1]) for m in messages]


def _ensure_csrf_token(request: Request) -> str:
    if "csrf_token" not in request.session:
        import secrets as _secrets
        request.session["csrf_token"] = _secrets.token_hex(32)
    return request.session["csrf_token"]


def _template_context(request: Request, user: User | None, **kwargs):
    return {
        "request": request,
        "user": user,
        "csrf_token": _ensure_csrf_token(request),
        "get_flashed_messages": lambda: _get_flashed_messages(request),
        "has_management_access": getattr(request.state, "has_management_access", False) if hasattr(request, "state") else False,
        "is_impersonating": bool(request.session.get("impersonating_from")),
        "dev_mode": settings.development,
        "smtp_from": settings.smtp_from,
        **kwargs,
    }


# --- Landing page ---


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)

    # Show public events for everyone; org events for members
    stmt = select(Event).where(
        Event.archived_at.is_(None),
        Event.visibility == EventVisibility.public,
    ).order_by(Event.date.asc())
    result = await db.execute(stmt)
    events = list(result.scalars().all())

    return templates.TemplateResponse(
        "index.html",
        _template_context(request, user, events=events),
    )


# --- Login ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: AsyncSession = Depends(get_db)):
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
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

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


# --- Event pages ---


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
    result = await db.execute(
        select(Event).where(
            Event.invite_code == invite_code,
            Event.archived_at.is_(None),
        )
    )
    event = result.scalar_one_or_none()

    reg_cutoff = event.rsvp_cutoff if event else None
    if reg_cutoff is not None and reg_cutoff.tzinfo is None:
        reg_cutoff = reg_cutoff.replace(tzinfo=UTC)
    if event is None or (reg_cutoff and reg_cutoff < datetime.now(UTC)):
        return templates.TemplateResponse(
            "link_sent.html",
            _template_context(
                request, None,
                invite_code=invite_code,
                token_expiry_hours=settings.token_expiry_hours,
            ),
        )

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

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


# --- RSVP ---


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
            _template_context(request, user, title="Event Not Found", message="This event doesn't exist."),
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

    # Load household members with live user preferences
    household_members = []
    if user.household_id:
        result = await db.execute(
            select(HouseholdMember)
            .where(HouseholdMember.household_id == user.household_id)
            .order_by(HouseholdMember.created_at)
        )
        household_members = list(result.scalars().all())

        for hm in household_members:
            if hm.user_id:
                lr = await db.execute(select(User).where(User.id == hm.user_id))
                linked = lr.scalar_one_or_none()
                if linked:
                    hm._live_name = linked.display_name or linked.email
                    hm._live_food = linked.food_preference
                    hm._live_dietary = linked.dietary_restrictions
                    hm._live_alcohol = linked.alcohol
                else:
                    hm._live_name = None
            else:
                hm._live_name = None

    # Determine checked state from existing RSVP
    self_checked = True
    checked_household_ids = set()
    extra_members = []

    if rsvp and rsvp.members:
        self_checked = any(m.is_self for m in rsvp.members)
        checked_household_ids = {
            str(m.household_member_id) for m in rsvp.members if m.household_member_id is not None
        }
        extra_members = [m for m in rsvp.members if not m.is_self and m.household_member_id is None]

    return templates.TemplateResponse(
        "rsvp_form.html",
        _template_context(
            request, user,
            event=event,
            rsvp=rsvp,
            household_members=household_members,
            self_checked=self_checked,
            checked_household_ids=checked_household_ids,
            extra_members=extra_members,
            readonly=past_cutoff and user.site_role.value < SiteRole.support.value,
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

    sub_cutoff = event.rsvp_cutoff
    if sub_cutoff is not None and sub_cutoff.tzinfo is None:
        sub_cutoff = sub_cutoff.replace(tzinfo=UTC)
    if (
        sub_cutoff
        and datetime.now(UTC) > sub_cutoff
        and user.site_role.value < SiteRole.support.value
    ):
        _flash(request, "error", "RSVP deadline has passed.")
        return RedirectResponse(url=f"/e/{invite_code}/rsvp", status_code=303)

    form = await request.form()
    attending_val = form.get("attending")
    attending = None
    if attending_val == "yes":
        attending = True
    elif attending_val == "no":
        attending = False

    notes = form.get("notes", "")

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
        from sqlalchemy import delete as sa_delete
        await db.execute(
            sa_delete(GuestGroupMember).where(GuestGroupMember.rsvp_id == rsvp.id)
        )
        await db.flush()

    new_members = []

    # Self
    if form.get("attending_self") == "1":
        user_result = await db.execute(select(User).where(User.id == user.id))
        db_user = user_result.scalar_one()
        member = GuestGroupMember(
            rsvp_id=rsvp.id,
            name=db_user.display_name or db_user.email,
            food_preference=db_user.food_preference,
            dietary_restrictions=db_user.dietary_restrictions,
            alcohol=db_user.alcohol,
            is_self=True,
        )
        db.add(member)
        new_members.append(member)

    # Household members
    if user.household_id:
        result = await db.execute(
            select(HouseholdMember)
            .where(HouseholdMember.household_id == user.household_id)
            .order_by(HouseholdMember.created_at)
        )
        household = list(result.scalars().all())
        for hm in household:
            if form.get(f"attending_household_{hm.id}") == "1":
                # For linked members, use their live user preferences
                name = hm.name
                food = hm.food_preference
                dietary = hm.dietary_restrictions
                alc = hm.alcohol
                if hm.user_id:
                    linked_result = await db.execute(
                        select(User).where(User.id == hm.user_id)
                    )
                    linked_user = linked_result.scalar_one_or_none()
                    if linked_user:
                        name = linked_user.display_name or linked_user.email
                        food = linked_user.food_preference
                        dietary = linked_user.dietary_restrictions
                        alc = linked_user.alcohol

                member = GuestGroupMember(
                    rsvp_id=rsvp.id,
                    name=name,
                    food_preference=food,
                    dietary_restrictions=dietary,
                    alcohol=alc,
                    household_member_id=hm.id,
                )
                db.add(member)
                new_members.append(member)

    # Extra guests
    extra_names = form.getlist("extra_name[]")
    extra_food = form.getlist("extra_food_preference[]")
    extra_dietary = form.getlist("extra_dietary_restrictions[]")
    for i, name in enumerate(extra_names):
        if not name.strip():
            continue
        alcohol = form.get(f"extra_alcohol_{i}") == "1"
        member = GuestGroupMember(
            rsvp_id=rsvp.id,
            name=name.strip(),
            food_preference=extra_food[i] if i < len(extra_food) and extra_food[i] else None,
            dietary_restrictions=extra_dietary[i] if i < len(extra_dietary) and extra_dietary[i] else None,
            alcohol=alcohol,
        )
        db.add(member)
        new_members.append(member)

    rsvp.total_guests = max(len(new_members), 1)
    await db.commit()

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


# --- Profile ---


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    # Load household info
    household = None
    household_members = []
    if user.household_id:
        result = await db.execute(
            select(Household).where(Household.id == user.household_id)
        )
        household = result.scalar_one_or_none()
        if household:
            result = await db.execute(
                select(HouseholdMember)
                .where(HouseholdMember.household_id == household.id)
                .order_by(HouseholdMember.created_at)
            )
            household_members = list(result.scalars().all())

            # For linked members, overlay live user preferences
            for hm in household_members:
                if hm.user_id:
                    result = await db.execute(
                        select(User).where(User.id == hm.user_id)
                    )
                    linked = result.scalar_one_or_none()
                    if linked:
                        hm._live_name = linked.display_name or linked.email
                        hm._live_food = linked.food_preference
                        hm._live_dietary = linked.dietary_restrictions
                        hm._live_alcohol = linked.alcohol
                    else:
                        hm._live_name = None
                else:
                    hm._live_name = None

    return templates.TemplateResponse(
        "profile.html",
        _template_context(
            request, user,
            household=household,
            household_members=household_members,
        ),
    )


@router.post("/profile")
async def profile_update(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()

    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.display_name = (form.get("display_name", "") or "").strip() or None
    db_user.food_preference = form.get("food_preference", "").strip() or None
    db_user.dietary_restrictions = form.get("dietary_restrictions", "").strip() or None
    db_user.alcohol = form.get("alcohol") == "1"

    # Sync linked household member row with updated preferences
    if db_user.household_id:
        result = await db.execute(
            select(HouseholdMember).where(
                HouseholdMember.household_id == db_user.household_id,
                HouseholdMember.user_id == db_user.id,
            )
        )
        hm = result.scalar_one_or_none()
        if hm:
            hm.name = db_user.display_name or db_user.email
            hm.food_preference = db_user.food_preference
            hm.dietary_restrictions = db_user.dietary_restrictions
            hm.alcohol = db_user.alcohol

    await db.commit()
    _flash(request, "success", "Profile updated.")
    return RedirectResponse(url="/profile", status_code=303)


# --- Household page routes ---


@router.post("/household/create")
async def household_create(
    request: Request,
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if user.household_id is not None:
        _flash(request, "error", "You already belong to a household.")
        return RedirectResponse(url="/profile", status_code=303)

    household = Household(name=name)
    db.add(household)
    await db.flush()

    member = HouseholdMember(
        household_id=household.id,
        user_id=user.id,
        name=user.display_name or user.email,
        food_preference=user.food_preference,
        dietary_restrictions=user.dietary_restrictions,
        alcohol=user.alcohol,
    )
    db.add(member)

    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.household_id = household.id

    await db.commit()
    _flash(request, "success", f"Household '{name}' created.")
    return RedirectResponse(url="/profile", status_code=303)


@router.get("/household/join/{invite_code}", response_class=HTMLResponse)
async def household_join_page(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    result = await db.execute(
        select(Household).where(Household.invite_code == invite_code)
    )
    household = result.scalar_one_or_none()
    if household is None:
        return templates.TemplateResponse(
            "error.html",
            _template_context(request, user, title="Not Found", message="Invalid household invite code."),
            status_code=404,
        )

    return templates.TemplateResponse(
        "household_join.html",
        _template_context(request, user, household=household),
    )


@router.post("/household/join/{invite_code}")
async def household_join(
    invite_code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None:
        return RedirectResponse(url="/login", status_code=303)

    if user.household_id is not None:
        _flash(request, "error", "You already belong to a household.")
        return RedirectResponse(url="/profile", status_code=303)

    result = await db.execute(
        select(Household).where(Household.invite_code == invite_code)
    )
    household = result.scalar_one_or_none()
    if household is None:
        _flash(request, "error", "Invalid invite code.")
        return RedirectResponse(url="/profile", status_code=303)

    member = HouseholdMember(
        household_id=household.id,
        user_id=user.id,
        name=user.display_name or user.email,
        food_preference=user.food_preference,
        dietary_restrictions=user.dietary_restrictions,
        alcohol=user.alcohol,
    )
    db.add(member)

    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.household_id = household.id

    await db.commit()
    _flash(request, "success", f"Joined household '{household.name}'.")
    return RedirectResponse(url="/profile", status_code=303)


@router.post("/household/members/add")
async def household_add_member(
    request: Request,
    name: str = Form(...),
    food_preference: str = Form(""),
    dietary_restrictions: str = Form(""),
    alcohol: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None or user.household_id is None:
        return RedirectResponse(url="/profile", status_code=303)

    member = HouseholdMember(
        household_id=user.household_id,
        name=name.strip(),
        food_preference=food_preference.strip() or None,
        dietary_restrictions=dietary_restrictions.strip() or None,
        alcohol=alcohol == "1",
    )
    db.add(member)
    await db.commit()
    _flash(request, "success", f"Added {name} to household.")
    return RedirectResponse(url="/profile", status_code=303)


@router.post("/household/members/{member_id}/remove")
async def household_remove_member(
    member_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_none(request, db)
    if user is None or user.household_id is None:
        return RedirectResponse(url="/profile", status_code=303)

    result = await db.execute(
        select(HouseholdMember).where(
            HouseholdMember.id == uuid.UUID(member_id),
            HouseholdMember.household_id == user.household_id,
        )
    )
    member = result.scalar_one_or_none()
    if member and member.user_id != user.id:
        await db.delete(member)
        await db.commit()
        _flash(request, "success", f"Removed {member.name} from household.")
    elif member and member.user_id == user.id:
        _flash(request, "error", "You can't remove yourself.")

    return RedirectResponse(url="/profile", status_code=303)


@router.post("/logout")
async def logout_page(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
