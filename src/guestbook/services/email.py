"""Email sending service — console, SMTP, and dev-mode backends."""

import logging
import smtplib
from collections import deque
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from guestbook.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)

# In-memory store for recent emails in development mode (max 50)
_recent_emails: deque[dict] = deque(maxlen=50)


def get_recent_emails() -> list[dict]:
    """Return recent emails captured in development mode (newest first)."""
    return list(reversed(_recent_emails))


def _capture_email(email: str, subject: str, url: str | None = None) -> None:
    """Store an email in the in-memory dev log."""
    _recent_emails.append({
        "to": email,
        "subject": subject,
        "url": url,
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    })


def _use_console() -> bool:
    """Determine if we should use console backend instead of SMTP."""
    if settings.development:
        return True
    return settings.mail_backend == "console"


def send_magic_link(email: str, url: str) -> None:
    """Send a magic link to the given email address."""
    if _use_console():
        _send_console(email, url)
        _capture_email(email, "Magic Link", url)
    else:
        subject = "Your Guestbook Login Link"
        html = _jinja_env.get_template("access_link.html").render(url=url)
        _send_smtp(email, subject, html)


def send_notification_email(email: str, subject: str, html_body: str) -> None:
    """Send a notification email."""
    if _use_console():
        logger.info("Notification to %s: %s", email, subject)
        print(
            f"\n{'=' * 60}\n"
            f"  Notification for {email}\n"
            f"  Subject: {subject}\n"
            f"{'=' * 60}\n"
        )
        _capture_email(email, subject)
    else:
        _send_smtp(email, subject, html_body)


def _send_console(email: str, url: str) -> None:
    """Print the magic link to stdout for development use."""
    logger.info("Magic link for %s: %s", email, url)
    print(
        f"\n{'=' * 60}\n"
        f"  Magic Link for {email}\n"
        f"  {url}\n"
        f"{'=' * 60}\n"
    )


def send_test_email(email: str) -> str:
    """Send a test email via SMTP to verify configuration. Returns status message."""
    if not settings.smtp_host or not settings.smtp_user:
        return "SMTP not configured. Set GUESTBOOK_SMTP_* env vars."

    html = "<h2>Guestbook Test Email</h2><p>If you're reading this, your SMTP configuration works!</p>"
    try:
        _send_smtp(email, "Guestbook — Test Email", html)
        return f"Test email sent to {email} via {settings.smtp_host}"
    except Exception as e:
        return f"Failed to send: {e}"


def _send_smtp(email: str, subject: str, html_body: str) -> None:
    """Send email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = email
    msg.attach(MIMEText(html_body, "html"))

    try:
        if settings.smtp_port == 465:
            # SSL (Resend, etc.)
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [email], msg.as_string())
        else:
            # STARTTLS (port 587, most providers)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
                if settings.smtp_user:
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from, [email], msg.as_string())
        logger.info("Email sent to %s: %s", email, subject)
    except Exception:
        logger.exception("Failed to send email to %s", email)
        raise
