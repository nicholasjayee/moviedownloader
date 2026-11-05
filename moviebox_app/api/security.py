from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse


class RequestBoundary:
    """Keep browser requests same-origin; the app is intended for local use."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            expected = f"{scope['scheme']}://{headers.get('host', '')}"
            if f"{parsed.scheme}://{parsed.netloc}" != expected:
                return await JSONResponse({"detail": "Cross-origin requests are blocked."}, 403)(
                    scope, receive, send
                )
        if headers.get("sec-fetch-site") == "cross-site":
            return await JSONResponse({"detail": "Cross-site requests are blocked."}, 403)(
                scope, receive, send
            )

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message["headers"]) + [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; style-src 'self'; "
                        b"script-src 'self'; connect-src 'self'; img-src 'self' data: https:; "
                        b"frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                ]
            await send(message)

        await self.app(scope, receive, secure_send)
