"""Reject oversized request bodies before they are read.

Configuration:
    GEOSPARK_MAX_BODY_BYTES = maximum request body size (default 1 MB)
"""

from __future__ import annotations

import os

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    """Pure ASGI middleware: 413 for bodies over the limit, declared or streamed."""

    def __init__(self, app: ASGIApp, max_bytes: int | None = None) -> None:
        self.app = app
        self.max_bytes = max_bytes or int(os.getenv("GEOSPARK_MAX_BODY_BYTES", str(1024 * 1024)))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        too_large = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds {self.max_bytes} bytes"},
        )
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await too_large(scope, receive, send)
                    return

        # Chunked uploads have no Content-Length: count bytes as they arrive.
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            await too_large(scope, receive, send)


class _BodyTooLargeError(Exception):
    pass
