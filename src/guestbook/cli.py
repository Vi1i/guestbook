import asyncio
import subprocess
import sys

import typer
import uvicorn

from guestbook.config import settings

app = typer.Typer(name="guestbook", help="Self-hosted RSVP website builder")


@app.callback()
def main() -> None:
    """Guestbook — self-hosted RSVP website builder."""


@app.command()
def init_db() -> None:
    """Run database migrations (alembic upgrade head)."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
    )
    if result.returncode != 0:
        raise typer.Exit(code=1)
    typer.echo("Database initialized successfully.")


@app.command()
def create_admin(
    email: str = typer.Option(..., help="Admin email address"),
) -> None:
    """Create a site admin user."""
    from sqlalchemy import select

    from guestbook.database import async_session
    from guestbook.models.user import SiteRole, User

    async def _create() -> None:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user is not None:
                user.site_role = SiteRole.admin
                await db.commit()
                typer.echo(f"Existing user {email} promoted to site admin.")
            else:
                user = User(email=email, site_role=SiteRole.admin)
                db.add(user)
                await db.commit()
                typer.echo(f"Site admin user created: {email}")

    asyncio.run(_create())


@app.command()
def create_event(
    title: str = typer.Option(..., help="Event title"),
    date: str = typer.Option(..., help="Event date (ISO format, e.g. 2026-07-04)"),
    org_slug: str = typer.Option(..., help="Organization slug"),
    location: str = typer.Option("", help="Event location"),
    description: str = typer.Option("", help="Event description"),
    visibility: str = typer.Option("private", help="Visibility: public or private"),
) -> None:
    """Create a new event within an organization."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from guestbook.database import async_session
    from guestbook.models.event import Event, EventVisibility
    from guestbook.models.organization import Organization

    parsed_date = datetime.fromisoformat(date)
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    async def _create() -> None:
        async with async_session() as db:
            result = await db.execute(
                select(Organization).where(Organization.slug == org_slug)
            )
            org = result.scalar_one_or_none()
            if org is None:
                typer.echo(f"Error: Organization '{org_slug}' not found.", err=True)
                raise typer.Exit(code=1)

            event = Event(
                org_id=org.id,
                title=title,
                date=parsed_date,
                location=location,
                description=description,
                visibility=EventVisibility(visibility),
            )
            db.add(event)
            await db.commit()
            await db.refresh(event)
            typer.echo(f"Event created: {event.title}")
            typer.echo(f"Invite code: {event.invite_code}")
            typer.echo(f"Event ID: {event.id}")

    asyncio.run(_create())


@app.command()
def create_org(
    name: str = typer.Option(..., help="Organization name"),
    slug: str = typer.Option("", help="URL slug (auto-generated if blank)"),
    owner_email: str = typer.Option(..., help="Owner's email address"),
) -> None:
    """Create an organization and assign an owner."""
    import re

    from sqlalchemy import select

    from guestbook.database import async_session
    from guestbook.models.organization import OrgMembership, OrgRole, Organization
    from guestbook.models.user import User

    final_slug = slug.strip() if slug.strip() else name
    final_slug = re.sub(r"[^\w\s-]", "", final_slug.lower())
    final_slug = re.sub(r"[\s_]+", "-", final_slug).strip("-")[:255] or "org"

    async def _create() -> None:
        async with async_session() as db:
            # Check slug
            result = await db.execute(
                select(Organization).where(Organization.slug == final_slug)
            )
            if result.scalar_one_or_none():
                typer.echo(f"Error: Slug '{final_slug}' already exists.", err=True)
                raise typer.Exit(code=1)

            # Find owner
            result = await db.execute(select(User).where(User.email == owner_email))
            user = result.scalar_one_or_none()
            if user is None:
                typer.echo(f"Error: User '{owner_email}' not found.", err=True)
                raise typer.Exit(code=1)

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

            typer.echo(f"Organization created: {org.name}")
            typer.echo(f"Slug: {org.slug}")
            typer.echo(f"Owner: {owner_email}")

    asyncio.run(_create())


@app.command()
def generate_qr(
    invite_code: str = typer.Option(..., help="Event invite code"),
    output: str = typer.Option("qr.png", help="Output PNG file path"),
    size: int = typer.Option(10, help="QR code box size in pixels"),
) -> None:
    """Generate a QR code PNG for an event's invite link."""
    from sqlalchemy import select

    from guestbook.database import async_session
    from guestbook.models.event import Event
    from guestbook.services.qr import generate_qr_png

    async def _generate() -> None:
        async with async_session() as db:
            result = await db.execute(
                select(Event).where(Event.invite_code == invite_code)
            )
            event = result.scalar_one_or_none()
            if event is None:
                typer.echo(f"Error: No event found with invite code '{invite_code}'", err=True)
                raise typer.Exit(code=1)

            url = f"{settings.base_url}/e/{event.invite_code}"
            png_bytes = generate_qr_png(url, size=size)

            with open(output, "wb") as f:
                f.write(png_bytes)

            typer.echo(f"QR code saved to {output}")
            typer.echo(f"Encodes: {url}")

    asyncio.run(_generate())


@app.command()
def run(
    host: str = typer.Option(None, help="Bind host (default: from GUESTBOOK_HOST or 0.0.0.0)"),
    port: int = typer.Option(None, help="Bind port (default: from GUESTBOOK_PORT or 8000)"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
) -> None:
    """Start the Guestbook web server."""
    uvicorn.run(
        "guestbook.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="debug" if settings.debug else "info",
    )
