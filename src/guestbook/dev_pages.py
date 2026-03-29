"""Development-only routes. Only active when GUESTBOOK_DEVELOPMENT=true."""

import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from guestbook.api.deps import get_db
from guestbook.models.organization import OrgMembership
from guestbook.models.user import SiteRole, User
from guestbook.pages import _flash, _get_user_or_none, _template_context
from guestbook.services.email import get_recent_emails, send_test_email

_BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent

router = APIRouter(prefix="/dev")
templates = Jinja2Templates(directory=_BASE_DIR / "templates")


@router.get("/login", response_class=HTMLResponse)
async def dev_login_page(request: Request, db: AsyncSession = Depends(get_db)):
    """Show all users with one-click login buttons."""
    user = await _get_user_or_none(request, db)

    result = await db.execute(select(User).order_by(User.site_role.desc(), User.email))
    users = list(result.scalars().all())

    # Load org memberships for display
    user_orgs = {}
    for u in users:
        result = await db.execute(
            select(OrgMembership)
            .options(selectinload(OrgMembership.organization))
            .where(OrgMembership.user_id == u.id)
        )
        user_orgs[str(u.id)] = list(result.scalars().all())

    recent_emails = get_recent_emails()

    return templates.TemplateResponse(
        "dev/login.html",
        _template_context(request, user, users=users, user_orgs=user_orgs, recent_emails=recent_emails),
    )


@router.post("/login/{user_id}")
async def dev_login_as(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Instantly log in as any user (dev mode only)."""
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/dev/login", status_code=303)

    # Clear any impersonation state
    request.session.pop("impersonating_from", None)

    request.session["user_id"] = str(target.id)
    request.session["site_role"] = target.site_role.value

    _flash(request, "success", f"Logged in as {target.email}")
    return RedirectResponse(url="/", status_code=303)


@router.post("/impersonate/{user_id}")
async def dev_impersonate(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Impersonate another user. Saves original user for switching back."""
    current_user = await _get_user_or_none(request, db)
    if current_user is None:
        return RedirectResponse(url="/dev/login", status_code=303)

    # Only site admins can impersonate (even in dev mode)
    if current_user.site_role.value < SiteRole.admin.value:
        _flash(request, "error", "Only site admins can impersonate users.")
        return RedirectResponse(url="/dev/login", status_code=303)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/dev/login", status_code=303)

    # Save original user so we can switch back
    request.session["impersonating_from"] = str(current_user.id)
    request.session["user_id"] = str(target.id)
    request.session["site_role"] = target.site_role.value

    _flash(request, "success", f"Now impersonating {target.email}")
    return RedirectResponse(url="/", status_code=303)


@router.post("/stop-impersonating")
async def dev_stop_impersonating(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Switch back to the original admin user."""
    original_id = request.session.get("impersonating_from")
    if not original_id:
        return RedirectResponse(url="/", status_code=303)

    result = await db.execute(select(User).where(User.id == uuid.UUID(original_id)))
    original = result.scalar_one_or_none()
    if original is None:
        request.session.clear()
        return RedirectResponse(url="/", status_code=303)

    request.session.pop("impersonating_from", None)
    request.session["user_id"] = str(original.id)
    request.session["site_role"] = original.site_role.value

    _flash(request, "success", f"Back to {original.email}")
    return RedirectResponse(url="/", status_code=303)


@router.post("/create-user")
async def dev_create_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Quick-create a user from the dev login page."""
    form = await request.form()
    email = form.get("email", "").strip()
    site_role = int(form.get("site_role", "1"))

    if not email:
        _flash(request, "error", "Email is required.")
        return RedirectResponse(url="/dev/login", status_code=303)

    result = await db.execute(select(User).where(User.email == email))
    if result.scalar_one_or_none():
        _flash(request, "error", f"{email} already exists.")
        return RedirectResponse(url="/dev/login", status_code=303)

    user = User(email=email, site_role=SiteRole(site_role))
    db.add(user)
    await db.commit()
    _flash(request, "success", f"User {email} created.")
    return RedirectResponse(url="/dev/login", status_code=303)


@router.post("/test-email")
async def dev_test_email(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Send a real test email via SMTP (bypasses dev console override)."""
    form = await request.form()
    email = form.get("email", "").strip()
    if not email:
        _flash(request, "error", "Email is required.")
        return RedirectResponse(url="/dev/login", status_code=303)

    result = send_test_email(email)
    _flash(request, "info", result)
    return RedirectResponse(url="/dev/login", status_code=303)
