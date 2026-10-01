"""The gateway's last word on an HTTP request that raised (#230).

Inside CORS, so even a crash answers with the CORS headers a browser needs to read
it. The error is re-raised so the server logs it once and TestClient still raises; the
re-raised error carries only the original type name, because a message may carry
session or user content.
"""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .log_safety import RedactedServerError

_BODY = json.dumps({"detail": "Internal server error"}).encode()


class UnhandledErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as error:
            if not started:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(_BODY)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": _BODY})
            raise RedactedServerError(type(error).__name__).with_traceback(
                error.__traceback__
            ) from None
