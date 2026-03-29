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
    """Create an admin user."""
    from sqlalchemy import select

    from guestbook.database import async_session
    from guestbook.models.user import Role, User

    async def _create() -> None:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()
            if user is not None:
                user.role = Role.admin
                await db.commit()
                typer.echo(f"Existing user {email} promoted to admin.")
            else:
                user = User(email=email, role=Role.admin)
                db.add(user)
                await db.commit()
                typer.echo(f"Admin user created: {email}")

    asyncio.run(_create())


@app.command()
def create_event(
    title: str = typer.Option(..., help="Event title"),
    date: str = typer.Option(..., help="Event date (ISO format, e.g. 2026-07-04)"),
    location: str = typer.Option("", help="Event location"),
    description: str = typer.Option("", help="Event description"),
) -> None:
    """Create a new event and print its invite code."""
    from datetime import datetime, timezone

    from guestbook.database import async_session
    from guestbook.models.event import Event

    parsed_date = datetime.fromisoformat(date)
    if parsed_date.tzinfo is None:
        parsed_date = parsed_date.replace(tzinfo=timezone.utc)

    async def _create() -> None:
        async with async_session() as db:
            event = Event(
                title=title,
                date=parsed_date,
                location=location,
                description=description,
            )
            db.add(event)
            await db.commit()
            await db.refresh(event)
            typer.echo(f"Event created: {event.title}")
            typer.echo(f"Invite code: {event.invite_code}")
            typer.echo(f"Event ID: {event.id}")

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
