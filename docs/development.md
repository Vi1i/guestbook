# Development Setup

## Prerequisites

- **Python 3.12+**
- **[UV](https://docs.astral.sh/uv/)** — fast Python package manager

## Getting Started

Clone the repo and install dependencies:

```bash
git clone <your-repo-url> guestbook
cd guestbook
uv sync --extra dev
```

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and set `GUESTBOOK_SECRET_KEY` to any random string (for local dev, the default is fine).

## Database

Initialize the SQLite database:

```bash
uv run guestbook init-db
```

This runs Alembic migrations and creates `guestbook.db` in the project root.

### Creating seed data

Create an admin user:

```bash
uv run guestbook create-admin --email admin@example.com
```

Create a test event:

```bash
uv run guestbook create-event --title "BBQ" --date 2026-07-04 --location "Backyard"
```

The command prints the invite code (e.g. `a3f8b2c1`) which you use to access the event at `http://localhost:8000/e/a3f8b2c1`.

## Running the Dev Server

```bash
uv run guestbook run --reload
```

The app is available at `http://localhost:8000`. The `--reload` flag enables auto-reload on file changes.

API docs are at `http://localhost:8000/docs` (Swagger) and `http://localhost:8000/redoc`.

### Console email backend

By default, `GUESTBOOK_MAIL_BACKEND=console`. Magic login links are printed to the terminal instead of sent via email. Look for output like:

```
============================================================
  Magic Link for guest@example.com
  http://localhost:8000/api/v1/auth/verify/abc123?invite_code=a3f8b2c1
============================================================
```

Copy and open that URL in your browser to log in.

## Running Tests

```bash
uv run pytest tests/ -v
```

Tests use an isolated SQLite file database. No external services required.

### Test structure

| File | Coverage |
|------|----------|
| `tests/test_auth.py` | Magic link request, token verify, expiry, replay, logout |
| `tests/test_events.py` | CRUD, invite codes, archive/unarchive, RBAC |
| `tests/test_rsvp.py` | Upsert, member replacement, cutoff enforcement, data isolation |
| `tests/test_admin.py` | User list, role changes, deletion cascade, permission checks |

## Project Layout

```
src/guestbook/
├── app.py              # FastAPI app factory, middleware, error handlers
├── config.py           # Pydantic Settings (env vars)
├── database.py         # SQLAlchemy async engine/session
├── cli.py              # Typer CLI commands
├── pages.py            # Guest-facing page routes (/, /e/{code}, /e/{code}/rsvp)
├── admin_pages.py      # Admin page routes (/admin/*)
├── middleware.py        # Security headers (pure ASGI)
├── models/             # SQLAlchemy ORM models
│   ├── user.py         # User, Role enum
│   ├── event.py        # Event with invite codes
│   ├── rsvp.py         # RSVP, GuestGroupMember
│   ├── token.py        # AccessToken (magic links)
│   └── notification.py # NotificationLog
├── schemas/            # Pydantic request/response models
├── api/                # JSON API routes (/api/v1/*)
│   ├── auth.py         # Magic link request + verify
│   ├── events.py       # Event CRUD
│   ├── rsvps.py        # RSVP operations + CSV export
│   ├── admin.py        # User management
│   ├── guests.py       # Per-event guest pre-registration
│   └── qr.py           # QR code generation
├── services/           # Business logic
│   ├── auth.py         # Token generation/verification
│   ├── email.py        # Console + SMTP email backends
│   ├── notification.py # Event change notifications
│   └── qr.py           # QR code PNG generation
├── templates/          # Jinja2 HTML templates (Pico CSS)
└── static/             # CSS and JS assets
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `guestbook init-db` | Run Alembic migrations |
| `guestbook create-admin --email EMAIL` | Create or promote an admin user |
| `guestbook create-event --title T --date D [--location L] [--description D]` | Create an event, prints invite code |
| `guestbook generate-qr --invite-code CODE [--output FILE] [--size N]` | Generate a QR code PNG |
| `guestbook run [--host H] [--port P] [--reload]` | Start the web server |

## Adding Migrations

After modifying models:

```bash
uv run alembic revision --autogenerate -m "describe your change"
uv run alembic upgrade head
```

## Environment Variables

All settings use the `GUESTBOOK_` prefix. See `.env.example` for the full list. Key ones for development:

| Variable | Default | Notes |
|----------|---------|-------|
| `GUESTBOOK_SECRET_KEY` | `change-me-in-production` | Session signing key |
| `GUESTBOOK_DEBUG` | `false` | Set to `true` for verbose logs and non-secure cookies |
| `GUESTBOOK_DATABASE_URL` | `sqlite+aiosqlite:///./guestbook.db` | SQLite or PostgreSQL |
| `GUESTBOOK_MAIL_BACKEND` | `console` | `console` or `smtp` |
