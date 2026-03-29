"""Site admin page routes (server-rendered)."""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from guestbook.api.deps import get_db
from guestbook.config import settings
from guestbook.models.organization import Organization
from guestbook.models.user import SiteRole, User
from guestbook.pages import _flash, _get_user_or_none, _md_filter, _template_context
from guestbook.services.auth import create_access_token
from guestbook.services.email import send_magic_link

_BASE_DIR = Path(__file__).resolve().parent

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=_BASE_DIR / "templates")
templates.env.filters["markdown"] = _md_filter


def _require_site_support(user: User | None):
    """Check if user has at least site support role."""
    if user is None:
        return False
    return user.site_role.value >= SiteRole.support.value


def _require_site_admin(user: User | None):
    if user is None:
        return False
    return user.site_role.value >= SiteRole.admin.value


# --- Login ---


@router.get("/login", response_class=HTMLResponse)
async def admin_login(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if user is not None and _require_site_support(user):
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
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is not None and user.site_role.value >= SiteRole.support.value:
        raw_token = await create_access_token(db, user)
        verify_url = f"{settings.base_url}/api/v1/auth/verify/{raw_token}?next=/admin"
        send_magic_link(email, verify_url)

    _flash(request, "success", "If that email belongs to a site admin, a login link has been sent.")
    return templates.TemplateResponse(
        "admin/login.html",
        _template_context(request, None),
    )


# --- Dashboard ---


@router.get("", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if not _require_site_support(user):
        return RedirectResponse(url="/admin/login", status_code=303)

    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(10))
    recent_users = list(result.scalars().all())

    result = await db.execute(select(Organization).order_by(Organization.name))
    orgs = list(result.scalars().all())

    from sqlalchemy import func
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar()

    return templates.TemplateResponse(
        "admin/dashboard.html",
        _template_context(
            request, user,
            recent_users=recent_users,
            orgs=orgs,
            user_count=user_count,
        ),
    )


# --- User management ---


@router.get("/users", response_class=HTMLResponse)
async def user_list(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_user_or_none(request, db)
    if not _require_site_admin(user):
        return RedirectResponse(url="/admin", status_code=303)

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
    site_role: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    admin = await _get_user_or_none(request, db)
    if not _require_site_admin(admin):
        return RedirectResponse(url="/admin", status_code=303)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/admin/users", status_code=303)

    target.site_role = SiteRole(site_role)
    await db.commit()
    _flash(request, "success", f"Role for {target.email} updated to {target.site_role.name}.")
    return RedirectResponse(url="/admin/users", status_code=303)


@router.post("/users/{user_id}/delete")
async def user_delete(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin = await _get_user_or_none(request, db)
    if not _require_site_admin(admin):
        return RedirectResponse(url="/admin", status_code=303)

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    target = result.scalar_one_or_none()
    if target is None:
        _flash(request, "error", "User not found.")
        return RedirectResponse(url="/admin/users", status_code=303)

    email = target.email
    await db.delete(target)
    await db.commit()
    _flash(request, "success", f"User {email} deleted.")
    return RedirectResponse(url="/admin/users", status_code=303)
