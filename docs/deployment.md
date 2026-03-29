# Site Setup & Deployment

This guide covers deploying Guestbook on a home lab server.

## Quick Start (Docker)

```bash
# Clone and configure
git clone <your-repo-url> guestbook
cd guestbook
cp .env.example .env
```

Edit `.env` with production values:

```bash
GUESTBOOK_SECRET_KEY=<generate with: python3 -c "import secrets; print(secrets.token_hex(32))">
GUESTBOOK_BASE_URL=https://rsvp.yourdomain.com
GUESTBOOK_MAIL_BACKEND=console   # or smtp
```

Build and start:

```bash
docker compose up -d --build
```

Initialize the database and create an admin:

```bash
docker compose exec guestbook uv run guestbook init-db
docker compose exec guestbook uv run guestbook create-admin --email you@example.com
```

The app is running at `http://localhost:8000`.

## With PostgreSQL

To use PostgreSQL instead of SQLite:

```bash
# Add to .env:
GUESTBOOK_DATABASE_URL=postgresql+asyncpg://guestbook:changeme@postgres/guestbook
POSTGRES_PASSWORD=changeme

# Start with the postgres profile:
docker compose --profile postgres up -d --build
```

Then initialize the database as above.

## Reverse Proxy (nginx)

An example nginx config is provided at `nginx.example.conf`. To set it up:

1. Copy to nginx sites:

   ```bash
   sudo cp nginx.example.conf /etc/nginx/sites-available/guestbook
   sudo ln -s /etc/nginx/sites-available/guestbook /etc/nginx/sites-enabled/
   ```

2. Replace `YOUR_DOMAIN` with your actual domain in the config file.

3. Obtain an SSL certificate:

   ```bash
   sudo certbot certonly --nginx -d rsvp.yourdomain.com
   ```

4. Test and reload:

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

The nginx config provides:
- HTTP to HTTPS redirect
- SSL termination with Let's Encrypt
- Proper `X-Forwarded-For` / `X-Forwarded-Proto` headers
- HSTS header
- WebSocket passthrough (for future use)

The app reads forwarded headers via uvicorn's `--proxy-headers` flag, which is enabled by default.

## Without Docker

Install UV and Python 3.12+, then:

```bash
uv sync
cp .env.example .env
# Edit .env with your settings

uv run guestbook init-db
uv run guestbook create-admin --email you@example.com
uv run guestbook run --host 0.0.0.0 --port 8000
```

For production, run behind a process manager like systemd:

```ini
# /etc/systemd/system/guestbook.service
[Unit]
Description=Guestbook RSVP Server
After=network.target

[Service]
User=guestbook
WorkingDirectory=/opt/guestbook
EnvironmentFile=/opt/guestbook/.env
ExecStart=/opt/guestbook/.venv/bin/guestbook run --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Creating Your First Event

Once the app is running and you have an admin account:

### Via CLI

```bash
# If using Docker:
docker compose exec guestbook uv run guestbook create-event \
  --title "Summer BBQ" \
  --date "2026-07-04T17:00:00" \
  --location "123 Main St" \
  --description "Bring your favorite dish!"

# Output:
# Event created: Summer BBQ
# Invite code: a3f8b2c1
# Event ID: ...
```

### Via Admin UI

1. Log in as admin (request a magic link at any event page, or via the API)
2. Go to `/admin/events/new`
3. Fill in the event details and submit
4. The invite code and share link are shown on the edit page

### Sharing the Event

The invite link is `https://yourdomain.com/e/{invite_code}`. Share it directly or generate a QR code:

```bash
# CLI:
docker compose exec guestbook uv run guestbook generate-qr \
  --invite-code a3f8b2c1 --output /app/data/bbq-qr.png

# Or via the API (manager+ role):
# GET /api/v1/events/{event_id}/qr
```

The QR code encodes the invite link and can be printed on physical invitations.

## Guest Flow

1. Guest scans QR code or follows the invite link
2. Lands on `/e/{invite_code}` — sees event details
3. Enters their email and submits
4. Receives a magic login link (printed to console in dev, or via email in production)
5. Clicks the link — authenticated and redirected to the RSVP form
6. Fills in attending status, group members, food preferences
7. Submits — sees a confirmation page
8. Can revisit and edit their RSVP until the cutoff

## Email Configuration

### Console (default)

Magic links and notifications are printed to stdout. Useful for development and when you want to manually share links.

### SMTP

```bash
GUESTBOOK_MAIL_BACKEND=smtp
GUESTBOOK_SMTP_HOST=smtp.example.com
GUESTBOOK_SMTP_PORT=587
GUESTBOOK_SMTP_USER=guestbook@example.com
GUESTBOOK_SMTP_PASSWORD=your-app-password
GUESTBOOK_SMTP_FROM=guestbook@example.com
```

The app sends two types of email:
- **Magic login links** — sent when a guest registers
- **Event update notifications** — sent to attending guests when event details change (if `notify_on_change` is enabled)

SMTP failures are logged but never crash the app.

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GUESTBOOK_SECRET_KEY` | *required* | Session cookie signing key |
| `GUESTBOOK_BASE_URL` | `http://localhost:8000` | Public URL for links and QR codes |
| `GUESTBOOK_DEBUG` | `false` | Debug mode (verbose logs, non-secure cookies) |
| `GUESTBOOK_DATABASE_URL` | `sqlite+aiosqlite:///./guestbook.db` | Database connection string |
| `GUESTBOOK_MAIL_BACKEND` | `console` | `console` or `smtp` |
| `GUESTBOOK_SMTP_HOST` | `localhost` | SMTP server hostname |
| `GUESTBOOK_SMTP_PORT` | `587` | SMTP server port |
| `GUESTBOOK_SMTP_USER` | *(empty)* | SMTP username |
| `GUESTBOOK_SMTP_PASSWORD` | *(empty)* | SMTP password |
| `GUESTBOOK_SMTP_FROM` | `guestbook@localhost` | Sender email address |
| `GUESTBOOK_SESSION_MAX_AGE` | `604800` | Session cookie lifetime (seconds, default 7 days) |
| `GUESTBOOK_TOKEN_EXPIRY_HOURS` | `24` | Magic link validity (hours) |
| `GUESTBOOK_RATE_LIMIT_AUTH` | `3/hour` | Rate limit on login link requests |

## Roles

| Role | Level | Can do |
|------|-------|--------|
| Guest | 1 | View events, submit/edit own RSVP |
| Manager | 2 | All guest abilities + edit events, view guest lists, archive, export CSV, generate QR |
| Admin | 3 | All manager abilities + create/delete events, manage users and roles |

The first user should be created as admin via `guestbook create-admin`. Additional users register through invite links and start as guests. Promote them via the admin UI at `/admin/users`.
