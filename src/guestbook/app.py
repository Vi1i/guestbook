import logging
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.sessions import SessionMiddleware

from guestbook.admin_pages import router as admin_router
from guestbook.api.router import api_router
from guestbook.config import settings
from guestbook.middleware import SecurityHeadersMiddleware
from guestbook.pages import router as pages_router

_BASE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

_templates = Jinja2Templates(directory=_BASE_DIR / "templates")


def _error_context(request: Request):
    return {
        "request": request,
        "user": None,
        "get_flashed_messages": lambda: [],
    }


def create_app() -> FastAPI:
    app = FastAPI(
        title="Guestbook",
        description="Self-hosted RSVP website builder",
        version="0.1.0",
        debug=settings.debug,
    )

    # Middleware — order matters: outermost first with add_middleware (LIFO)
    # SecurityHeaders wraps everything
    app.add_middleware(SecurityHeadersMiddleware)

    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=not settings.debug,
    )

    # Rate limiter state
    app.state.limiter = limiter

    # --- Error handlers ---

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        return _templates.TemplateResponse(
            "errors/404.html",
            _error_context(request),
            status_code=404,
        )

    @app.exception_handler(403)
    async def forbidden_handler(request: Request, exc):
        return _templates.TemplateResponse(
            "errors/403.html",
            _error_context(request),
            status_code=403,
        )

    @app.exception_handler(500)
    async def server_error_handler(request: Request, exc):
        logger.exception("Internal server error")
        return _templates.TemplateResponse(
            "errors/500.html",
            _error_context(request),
            status_code=500,
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return _templates.TemplateResponse(
            "errors/429.html",
            _error_context(request),
            status_code=429,
        )

    # Static files
    app.mount("/static", StaticFiles(directory=_BASE_DIR / "static"), name="static")

    # API routes
    app.include_router(api_router)

    # Admin page routes
    app.include_router(admin_router)

    # Server-rendered page routes
    app.include_router(pages_router)

    return app
