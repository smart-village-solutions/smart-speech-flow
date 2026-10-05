"""Short-lived, single-use capabilities for authenticated realtime transports."""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Callable, Literal, Protocol

from .clock import utc_now
from .tenant_session import TenantSessionKey

try:
    from redis.exceptions import RedisError
except ImportError:  # pragma: no cover - redis optional for tests

    class RedisError(Exception):  # type: ignore[no-redef]
        pass


# What a ticket backend can fail with: Redis itself, the socket under it, and a
# stored payload that no longer decodes. Each becomes RealtimeTicketUnavailable.
_BACKEND_FAILURES = (RedisError, OSError, ValueError)

RealtimeTransportKind = Literal["websocket", "polling"]

CONSUME_TICKET_LUA = """
local value = redis.call('GET', KEYS[1])
if value then redis.call('DEL', KEYS[1]) end
return value
"""


class RealtimeTicketUnavailable(RuntimeError):
    """The ticket store could not issue or consume a capability."""


@dataclass(frozen=True, slots=True)
class IssuedRealtimeTicket:
    ticket: str
    expires_at: datetime


def _ticket_hash(ticket: str) -> str:
    return sha256(ticket.encode("ascii")).hexdigest()


class RealtimeTicketBackend(Protocol):
    """The storage operations realtime tickets need, with a lifetime per key.

    `consume` is an atomic get-and-delete: however many callers race for one
    key, exactly one receives its value. That is what makes a ticket single
    use. `put` overwrites and restarts the lifetime, which revocation relies on.
    """

    async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool: ...

    async def put(self, key: str, value: str, ttl_seconds: int) -> None: ...

    async def consume(self, key: str) -> str | None: ...

    async def get(self, key: str) -> str | None: ...


class RealtimeTicketStore:
    def __init__(
        self,
        backend: RealtimeTicketBackend,
        *,
        namespace: str = "ssf",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.backend = backend
        self.namespace = namespace
        self.clock = clock

    def _key(self, ticket: str) -> str:
        return f"{self.namespace}:v2:realtime-ticket:{_ticket_hash(ticket)}"

    def _revoked_key(self, key: TenantSessionKey) -> str:
        return (
            f"{self.namespace}:v2:tenant:{key.redis_tenant_component}:"
            f"session:{key.session_id}:realtime-revoked"
        )

    async def revoke(self, key: TenantSessionKey) -> None:
        """Invalidate every outstanding ticket for one terminal session."""
        try:
            await self.backend.put(self._revoked_key(key), "1", 8 * 60 * 60)
        except _BACKEND_FAILURES as error:
            raise RealtimeTicketUnavailable() from error

    async def issue(
        self,
        key: TenantSessionKey,
        transport: RealtimeTransportKind,
        ttl_seconds: int = 60,
    ) -> IssuedRealtimeTicket:
        if not 1 <= ttl_seconds <= 60:
            raise ValueError("realtime ticket lifetime must be between 1 and 60 seconds")
        payload = json.dumps(
            {
                "role": "admin",
                "session_id": key.session_id,
                "tenant_id": key.tenant_id,
                "transport": transport,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        try:
            for _attempt in range(3):
                ticket = secrets.token_urlsafe(32)
                if await self.backend.put_if_absent(self._key(ticket), payload, ttl_seconds):
                    return IssuedRealtimeTicket(
                        ticket=ticket,
                        expires_at=self.clock() + timedelta(seconds=ttl_seconds),
                    )
        except _BACKEND_FAILURES as error:
            raise RealtimeTicketUnavailable() from error
        raise RealtimeTicketUnavailable()

    async def consume(
        self,
        raw_ticket: str,
        key: TenantSessionKey,
        transport: RealtimeTransportKind,
    ) -> bool:
        resolved = await self.consume_key(raw_ticket, key.session_id, transport)
        return resolved is not None and all(
            hmac.compare_digest(left, right)
            for left, right in (
                (resolved.tenant_id, key.tenant_id),
                (resolved.session_id, key.session_id),
            )
        )

    async def consume_key(
        self,
        raw_ticket: str,
        session_id: str,
        transport: RealtimeTransportKind,
    ) -> TenantSessionKey | None:
        """Consume a ticket and recover its server-issued tenant scope."""
        try:
            raw_payload = await self.backend.consume(self._key(raw_ticket))
            payload = json.loads(raw_payload) if raw_payload is not None else None
        except _BACKEND_FAILURES as error:
            raise RealtimeTicketUnavailable() from error
        if not isinstance(payload, dict):
            return None
        tenant_id = payload.get("tenant_id")
        payload_session_id = payload.get("session_id")
        role = payload.get("role")
        payload_transport = payload.get("transport")
        if not all(
            isinstance(value, str)
            for value in (tenant_id, payload_session_id, role, payload_transport)
        ):
            return None
        if not (
            hmac.compare_digest(payload_session_id, session_id)
            and hmac.compare_digest(role, "admin")
            and hmac.compare_digest(payload_transport, transport)
        ):
            return None
        try:
            resolved = TenantSessionKey(tenant_id, payload_session_id)
        except ValueError:
            return None
        try:
            if await self.backend.get(self._revoked_key(resolved)) is not None:
                return None
        except _BACKEND_FAILURES as error:
            raise RealtimeTicketUnavailable() from error
        return resolved


def _decoded(value: bytes | str | None) -> str | None:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class RedisRealtimeTicketBackend:
    """Tickets in Redis. The only code that knows about CONSUME_TICKET_LUA."""

    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        return bool(await self.redis.set(key, value, ex=ttl_seconds, nx=True))

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        await self.redis.set(key, value, ex=ttl_seconds, nx=False)

    async def consume(self, key: str) -> str | None:
        return _decoded(await self.redis.eval(CONSUME_TICKET_LUA, 1, key))

    async def get(self, key: str) -> str | None:
        return _decoded(await self.redis.get(key))


class MemoryRealtimeTicketBackend:
    """Process-local tickets for tests and local development without Redis.

    No method awaits, so each one runs to completion before another starts:
    that is what makes `consume` single use here.
    """

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self.values: dict[str, tuple[str, datetime]] = {}

    async def put_if_absent(self, key: str, value: str, ttl_seconds: int) -> bool:
        self._expire(key)
        if key in self.values:
            return False
        self._put(key, value, ttl_seconds)
        return True

    async def put(self, key: str, value: str, ttl_seconds: int) -> None:
        self._put(key, value, ttl_seconds)

    def _put(self, key: str, value: str, ttl_seconds: int) -> None:
        self.values[key] = (value, self.clock() + timedelta(seconds=ttl_seconds))

    async def consume(self, key: str) -> str | None:
        self._expire(key)
        stored = self.values.pop(key, None)
        return stored[0] if stored else None

    async def get(self, key: str) -> str | None:
        self._expire(key)
        stored = self.values.get(key)
        return stored[0] if stored else None

    def _expire(self, key: str) -> None:
        stored = self.values.get(key)
        if stored is not None and stored[1] <= self.clock():
            self.values.pop(key, None)
