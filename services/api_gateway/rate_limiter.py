"""In-memory rate limiting middleware for the API gateway."""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from typing import Deque, Dict, Optional, Tuple

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


@dataclass
class RateLimitConfig:
    """Configuration values for the rate limiting middleware."""

    global_limit: int = int(os.getenv("GLOBAL_RATE_LIMIT", "240"))
    global_window_seconds: int = int(os.getenv("GLOBAL_RATE_WINDOW_SECONDS", "60"))
    message_limit: int = int(os.getenv("MESSAGE_RATE_LIMIT", "12"))
    message_window_seconds: int = int(os.getenv("MESSAGE_RATE_WINDOW_SECONDS", "10"))


LATEST_RATE_LIMIT_MIDDLEWARE = None  # type: Optional["RateLimitMiddleware"]


class RateLimiter:
    """Simple sliding-window rate limiter that tracks recent request timestamps."""

    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> Tuple[bool, float]:
        """Return whether a request is allowed and the retry-after delay in seconds."""
        if self.max_requests <= 0:
            return True, 0.0

        now = time.monotonic()
        async with self._lock:
            entries = self._requests[key]
            window_start = now - self.window_seconds

            while entries and entries[0] < window_start:
                entries.popleft()

            if len(entries) < self.max_requests:
                entries.append(now)
                return True, 0.0

            retry_after = self.window_seconds - (now - entries[0])
            retry_after = max(0.0, retry_after)
            return False, retry_after

    async def reset(self) -> None:
        """Reset all recorded rate limiting data."""
        async with self._lock:
            self._requests.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces rate limits for API requests."""

    def __init__(self, app, config: Optional[RateLimitConfig] = None) -> None:
        super().__init__(app)
        self.config = config or RateLimitConfig()
        self.global_limiter = RateLimiter(
            self.config.global_limit,
            self.config.global_window_seconds,
        )
        self.message_limiter = RateLimiter(
            self.config.message_limit,
            self.config.message_window_seconds,
        )
        # expose middleware for runtime adjustments (tests, admin tooling)
        state = getattr(app, "state", None)
        if state is not None:
            setattr(state, "rate_limit_middleware", self)

        global LATEST_RATE_LIMIT_MIDDLEWARE
        LATEST_RATE_LIMIT_MIDDLEWARE = self

    async def dispatch(self, request: Request, call_next) -> Response:
        """Apply rate limiting before the request reaches the endpoint."""
        global LATEST_RATE_LIMIT_MIDDLEWARE
        if LATEST_RATE_LIMIT_MIDDLEWARE is not self:
            LATEST_RATE_LIMIT_MIDDLEWARE = self

        session_key = self._session_message_key(request)
        if session_key:
            allowed, retry_after = await self.message_limiter.check(session_key)
            if not allowed:
                return self._rate_limited_response(
                    error_code="SESSION_MESSAGE_RATE_LIMIT",
                    error_message="Too many messages for this session. Please slow down.",
                    retry_after=retry_after,
                    limit=self.config.message_limit,
                    window=self.config.message_window_seconds,
                    scope=session_key,
                )

        client_key = self._client_key(request)
        allowed, retry_after = await self.global_limiter.check(client_key)
        if not allowed:
            return self._rate_limited_response(
                error_code="GLOBAL_RATE_LIMIT_EXCEEDED",
                error_message="Too many requests. Please retry later.",
                retry_after=retry_after,
                limit=self.config.global_limit,
                window=self.config.global_window_seconds,
                scope=client_key,
            )

        return await call_next(request)

    @staticmethod
    def _client_key(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for") or request.headers.get(
            "x-real-ip"
        )
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host or "unknown"
        return "unknown"

    @staticmethod
    def _session_message_key(request: Request) -> Optional[str]:
        if request.method != "POST":
            return None

        path = request.url.path
        parts = [segment for segment in path.split("/") if segment]
        if (
            len(parts) >= 4
            and parts[0] == "api"
            and parts[1] == "session"
            and parts[3] == "message"
        ):
            session_id = parts[2]
            return f"session:{session_id}"
        return None

    @staticmethod
    def _rate_limited_response(
        *,
        error_code: str,
        error_message: str,
        retry_after: float,
        limit: int,
        window: int,
        scope: str,
    ) -> JSONResponse:
        retry_after_header = str(max(1, int(retry_after))) if retry_after else "1"
        content = {
            "status": "error",
            "error_code": error_code,
            "error_message": error_message,
            "details": {
                "limit": limit,
                "window_seconds": window,
                "scope": scope,
            },
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
        response = JSONResponse(status_code=429, content=content)
        response.headers["Retry-After"] = retry_after_header
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = "0"
        response.headers["X-RateLimit-Window"] = str(window)
        return response
