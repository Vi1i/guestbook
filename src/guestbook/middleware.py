"""Custom middleware implementations (pure ASGI, no BaseHTTPMiddleware)."""

import secrets
from starlette.types import ASGIApp, Receive, Scope, Send


class SecurityHeadersMiddleware:
    """Add security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                extra = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-frame-options", b"DENY"),
                    (b"x-xss-protection", b"1; mode=block"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"content-security-policy",
                     b"default-src 'self'; "
                     b"style-src 'self' https://cdn.jsdelivr.net; "
                     b"script-src 'self'; "
                     b"img-src 'self' data:; "
                     b"font-src 'self' https://cdn.jsdelivr.net"),
                ]
                existing = list(message.get("headers", []))
                existing.extend(extra)
                message = {**message, "headers": existing}
            await send(message)

        await self.app(scope, receive, send_with_headers)
