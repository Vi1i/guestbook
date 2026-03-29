"""Email sending service — console and SMTP backends."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from guestbook.config import settings

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def send_magic_link(email: str, url: str) -> None:
    """Send a magic link to the given email address."""
    if settings.mail_backend == "console":
        _send_console(email, url)
    else:
        subject = "Your Guestbook Login Link"
        html = _jinja_env.get_template("access_link.html").render(url=url)
        _send_smtp(email, subject, html)


def send_notification_email(email: str, subject: str, html_body: str) -> None:
    """Send a notification email."""
    if settings.mail_backend == "console":
        logger.info("Notification to %s: %s", email, subject)
        print(
            f"\n{'=' * 60}\n"
            f"  Notification for {email}\n"
            f"  Subject: {subject}\n"
            f"{'=' * 60}\n"
        )
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


def _send_smtp(email: str, subject: str, html_body: str) -> None:
    """Send email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, [email], msg.as_string())
        logger.info("Email sent to %s: %s", email, subject)
    except Exception:
        logger.exception("Failed to send email to %s", email)
        raise
