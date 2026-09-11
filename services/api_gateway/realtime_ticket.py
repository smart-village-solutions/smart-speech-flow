"""Short-lived, single-use capabilities for authenticated realtime transports."""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Callable, Literal

from .session_manager import utc_now
from .tenant_session import TenantSessionKey

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


class RealtimeTicketStore:
    def __init__(
        self,
        redis: Any,
        *,
        namespace: str = "ssf",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.redis = redis
        self.namespace = namespace
        self.clock = clock

    def _key(self, ticket: str) -> str:
        return f"{self.namespace}:v2:realtime-ticket:{_ticket_hash(ticket)}"

    def issue(
        self,
        key: TenantSessionKey,
        transport: RealtimeTransportKind,
        ttl_seconds: int = 60,
    ) -> IssuedRealtimeTicket:
        if not 1 <= ttl_seconds <= 60:
            raise ValueError(
                "realtime ticket lifetime must be between 1 and 60 seconds"
            )
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
                if self.redis.set(self._key(ticket), payload, ex=ttl_seconds, nx=True):
                    return IssuedRealtimeTicket(
                        ticket=ticket,
                        expires_at=self.clock() + timedelta(seconds=ttl_seconds),
                    )
        except Exception as error:
            raise RealtimeTicketUnavailable() from error
        raise RealtimeTicketUnavailable()

    def consume(
        self,
        raw_ticket: str,
        key: TenantSessionKey,
        transport: RealtimeTransportKind,
    ) -> bool:
        try:
            raw_payload = self.redis.eval(
                CONSUME_TICKET_LUA,
                1,
                self._key(raw_ticket),
            )
            if isinstance(raw_payload, bytes):
                raw_payload = raw_payload.decode("utf-8")
            payload = json.loads(raw_payload) if raw_payload is not None else None
        except Exception as error:
            raise RealtimeTicketUnavailable() from error
        if not isinstance(payload, dict):
            return False
        expected = {
            "role": "admin",
            "session_id": key.session_id,
            "tenant_id": key.tenant_id,
            "transport": transport,
        }
        return all(
            isinstance(payload.get(field), str)
            and hmac.compare_digest(payload[field], value)
            for field, value in expected.items()
        )


class MemoryRealtimeTicketBackend:
    """Minimal process-local Redis contract for tests and local development."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self.clock = clock
        self.values: dict[str, tuple[str, datetime]] = {}

    def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        self._expire(key)
        if nx and key in self.values:
            return False
        self.values[key] = (value, self.clock() + timedelta(seconds=ex))
        return True

    def eval(self, script: str, number_of_keys: int, key: str) -> str | None:
        self._expire(key)
        stored = self.values.pop(key, None)
        return stored[0] if stored else None

    def _expire(self, key: str) -> None:
        stored = self.values.get(key)
        if stored is not None and stored[1] <= self.clock():
            self.values.pop(key, None)


realtime_ticket_store = RealtimeTicketStore(MemoryRealtimeTicketBackend())
