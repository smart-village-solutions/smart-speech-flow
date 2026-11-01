"""Where each conversation's recording state lives: Redis beside the session (spec §5.1).

A gateway restart keeps the state, so a recording that was ON comes back as
PAUSED until both screens answer again, inside the same window. Only
conversations that are not OFF are indexed, so the ping loop visits those alone.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Final, Protocol

from ..session_store import session_key
from ..tenant_session import TenantSessionKey
from .session_state import Phase, Reason, RecordingState

# Longer than any session may live, so a state outlives its session only briefly.
STATE_TTL_SECONDS: Final[int] = 24 * 60 * 60
_SEPARATOR: Final[str] = "\x1f"
_TIMES: Final[tuple[str, ...]] = ("since", "id_checked_at")


class RecordingStateStore(Protocol):
    async def load(self, key: TenantSessionKey) -> RecordingState: ...

    async def save(self, key: TenantSessionKey, state: RecordingState) -> None: ...

    async def recording_sessions(self) -> list[TenantSessionKey]:
        """Every conversation whose state is not OFF."""
        ...

    async def touch(self, key: TenantSessionKey) -> None:
        """Restart the state's expiry while a screen still watches it."""
        ...


def encode_state(state: RecordingState) -> str:
    fields = asdict(state)
    fields["phase"] = state.phase.value
    fields["reason"] = state.reason.value if state.reason else None
    for name in _TIMES:
        at = getattr(state, name)
        fields[name] = at.isoformat() if at else None
    return json.dumps(fields, separators=(",", ":"), sort_keys=True)


def decode_state(raw: str) -> RecordingState:
    fields: dict[str, Any] = json.loads(raw)
    fields["phase"] = Phase(fields["phase"])
    fields["reason"] = Reason(fields["reason"]) if fields["reason"] else None
    for name in _TIMES:
        at = fields.get(name)
        fields[name] = datetime.fromisoformat(at) if at else None
    return RecordingState(**fields)


class MemoryRecordingStateStore:
    def __init__(self) -> None:
        self._states: dict[TenantSessionKey, str] = {}

    async def load(self, key: TenantSessionKey) -> RecordingState:
        raw = self._states.get(key)
        return RecordingState() if raw is None else decode_state(raw)

    async def save(self, key: TenantSessionKey, state: RecordingState) -> None:
        self._states[key] = encode_state(state)

    async def recording_sessions(self) -> list[TenantSessionKey]:
        return [
            key for key, raw in self._states.items() if decode_state(raw).phase is not Phase.OFF
        ]

    async def touch(self, key: TenantSessionKey) -> None:
        await asyncio.sleep(0)  # nothing expires in memory


class RedisRecordingStateStore:
    def __init__(self, redis: Any, *, namespace: str = "ssf") -> None:
        self._redis = redis
        self._namespace = namespace

    def _key(self, key: TenantSessionKey) -> str:
        return session_key(self._namespace, key) + ":recording"

    @property
    def _index(self) -> str:
        return f"{self._namespace}:v2:recording:active"

    async def load(self, key: TenantSessionKey) -> RecordingState:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return RecordingState()
        return decode_state(raw.decode() if isinstance(raw, bytes) else raw)

    async def save(self, key: TenantSessionKey, state: RecordingState) -> None:
        # One transaction: a state that is not OFF but missing from the index
        # would never time out, pause or be pinged.
        member = key.tenant_id + _SEPARATOR + key.session_id
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(self._key(key), encode_state(state), ex=STATE_TTL_SECONDS)
            if state.phase is Phase.OFF:
                pipe.srem(self._index, member)
            else:
                pipe.sadd(self._index, member)
            await pipe.execute()

    async def touch(self, key: TenantSessionKey) -> None:
        await self._redis.expire(self._key(key), STATE_TTL_SECONDS)

    async def recording_sessions(self) -> list[TenantSessionKey]:
        keys = []
        for member in await self._redis.smembers(self._index):
            text = member.decode() if isinstance(member, bytes) else member
            tenant_id, _, session_id = text.partition(_SEPARATOR)
            keys.append(TenantSessionKey(tenant_id, session_id))
        return keys
