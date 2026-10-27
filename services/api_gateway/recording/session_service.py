"""The gateway side of recording a live conversation (spec §5.1, §5.2, §14).

Holds each conversation's state under a per-session lock, announces every
transition to both screens, and runs the ping loop that keeps a recording
honest: while it is not OFF, both screens must answer within the liveness
window or ON turns PAUSED. The screens never decide the state; they only
acknowledge the version they render.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Final, Protocol

from ..clock import utc_now
from ..keyed_locks import KeyedLocks
from ..realtime_protocol import (
    Frame,
    recording_ping_frame,
    recording_request_frame,
    recording_state_frame,
)
from ..session_models import ClientType
from ..studio_v2 import RecordingPolicy
from ..tenant_session import TenantSessionKey
from . import session_state as rs
from .audit import AuditEvent
from .session_state import Phase, Reason, RecordingState, Snapshot
from .session_store import RecordingStateStore

logger = logging.getLogger(__name__)

TICK_SECONDS: Final[float] = 1.0
# A policy read the tick waits for; a slower Studio leaves the pause in place.
POLICY_READ_SECONDS: Final[float] = 1.0
GUEST_ACTOR: Final[str] = "guest"
SYSTEM_ACTOR: Final[str] = "system"
_ROLES: Final[tuple[ClientType, ClientType]] = (ClientType.ADMIN, ClientType.CUSTOMER)

PolicyReader = Callable[[str], Awaitable[RecordingPolicy | None]]
Send = Callable[[Frame], Awaitable[None]]


class RecordingUnavailableError(Exception):
    """Recording cannot start for this conversation; `code` is the wire error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Announcer(Protocol):
    async def broadcast(
        self, key: TenantSessionKey, frame: Frame, role: ClientType | None
    ) -> None: ...

    def connected(self, key: TenantSessionKey, role: ClientType) -> bool: ...


class RecordingSessions:
    def __init__(
        self,
        *,
        store: RecordingStateStore,
        announcer: Announcer,
        policy: PolicyReader,
        recovery_key_ready: Callable[[str], Awaitable[bool]],
        audit: Callable[[AuditEvent], Awaitable[None]],
        storage_ready: Callable[[TenantSessionKey], bool] = lambda _key: True,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._announcer = announcer
        self._policy = policy
        self._recovery_key_ready = recovery_key_ready
        self._audit = audit
        self._storage_ready = storage_ready
        self._clock = clock
        self._monotonic = monotonic
        self._locks: KeyedLocks[TenantSessionKey] = KeyedLocks()
        self._pongs: dict[tuple[TenantSessionKey, ClientType], float] = {}
        self._last_ping: dict[TenantSessionKey, float] = {}
        self._last_policy_read: dict[TenantSessionKey, float] = {}

    async def state(self, key: TenantSessionKey) -> RecordingState:
        return await self._store.load(key)

    async def check_available(self, tenant_id: str) -> None:
        """Raise unless this tenant may record now: a live, fail-closed read (§14)."""
        try:
            policy = await self._policy(tenant_id)
        except Exception:
            raise RecordingUnavailableError("RECORDING_POLICY_UNAVAILABLE") from None
        if policy is None or not policy.enabled:
            raise RecordingUnavailableError("RECORDING_DISABLED")
        if not await self._recovery_key_ready(tenant_id):
            raise RecordingUnavailableError("RECOVERY_KEY_MISSING")

    async def request(
        self, key: TenantSessionKey, *, request_id: str, requested_by: str
    ) -> RecordingState:
        current = await self._store.load(key)
        if current.request_id == request_id:
            return current  # a replay: the checks were made when it was new
        self._require_guest(key)
        await self.check_available(key.tenant_id)

        def transition(state: RecordingState, now: datetime) -> RecordingState:
            # Again under the lock: the guest may have left, or the session ended,
            # while the policy was read.
            self._require_guest(key)
            return rs.request(state, request_id=request_id, requested_by=requested_by, now=now)

        return await self._change(key, requested_by, transition)

    def _require_guest(self, key: TenantSessionKey) -> None:
        if not self._announcer.connected(key, ClientType.CUSTOMER):
            raise RecordingUnavailableError("GUEST_NOT_CONNECTED")

    async def cancel(self, key: TenantSessionKey, *, request_id: str, actor: str) -> RecordingState:
        return await self._change(
            key, actor, lambda state, now: rs.cancel(state, request_id=request_id, now=now)
        )

    async def answer(
        self, key: TenantSessionKey, *, request_id: str, consent: bool
    ) -> RecordingState:
        current = await self._store.load(key)
        if consent and current.phase is Phase.ASKING and current.request_id == request_id:
            # The policy is read again at the guest's yes; a failure refuses it.
            # A replay or a stale answer needs no read: the transition settles it.
            await self.check_available(key.tenant_id)
        window_id = str(uuid.uuid4())
        return await self._change(
            key,
            GUEST_ACTOR,
            lambda state, now: rs.answer(
                state, request_id=request_id, consent=consent, window_id=window_id, now=now
            ),
        )

    async def stop(self, key: TenantSessionKey, *, role: ClientType, actor: str) -> RecordingState:
        return await self._change(key, actor, lambda state, now: rs.stop(state, by=role, now=now))

    async def acknowledge(self, key: TenantSessionKey, role: ClientType, version: int) -> None:
        # An acknowledgement is a sign of life as good as a pong.
        self.pong(key, role)
        async with self._locks.hold(key):
            state = await self._store.load(key)
            acked = rs.acknowledge(state, role=role, version=version)
            if acked == state:
                return
            # A policy pause clears only on a fresh read, which the tick makes.
            ready = self._storage_ready(key) and acked.reason is not Reason.POLICY
            advanced = rs.advance(acked, now=self._clock(), live=self.live(key), ready=ready)
            await self._commit(key, state, advanced, SYSTEM_ACTOR)

    def pong(self, key: TenantSessionKey, role: ClientType) -> None:
        self._pongs[(key, role)] = self._monotonic()

    def released(self, key: TenantSessionKey, role: ClientType) -> None:
        """A socket of `role` closed. Once none is left, the role is gone now, not 12 s from now."""
        if not self._announcer.connected(key, role):
            self._pongs.pop((key, role), None)

    def live(self, key: TenantSessionKey) -> bool:
        now = self._monotonic()
        return all(
            now - self._pongs.get((key, role), float("-inf")) <= rs.LIVENESS_SECONDS
            for role in _ROLES
        )

    async def snapshot(self, key: TenantSessionKey) -> Snapshot:
        return rs.snapshot(await self._store.load(key), live=self.live(key))

    async def pause(self, key: TenantSessionKey, reason: Reason) -> None:
        await self._change(
            key, SYSTEM_ACTOR, lambda state, now: rs.pause(state, reason=reason, now=now)
        )

    async def greet(self, key: TenantSessionKey, role: ClientType, send: Send) -> None:
        """A screen that (re)connects learns the state, and a guest any open request."""
        try:
            await self._greet(key, role, send)
        except Exception as error:  # A failed greeting must not strand the socket it greets.
            logger.warning("recording_greeting_failed error=%s", type(error).__name__)

    async def _greet(self, key: TenantSessionKey, role: ClientType, send: Send) -> None:
        state = await self._store.load(key)
        await send(self._state_frame(key, state))
        if role is ClientType.CUSTOMER and state.phase is Phase.ASKING:
            await send(self._request_frame(key, state))
        if state.recording:
            # Its band counts as live only after a ping; the next might be 5 s away.
            await send(recording_ping_frame(key.session_id))

    async def session_ended(self, key: TenantSessionKey) -> None:
        async with self._locks.hold(key):
            state = await self._store.load(key)
            ended = rs.end(state, now=self._clock())
            if ended != state:
                await self._store.save(key, ended)
                await self._record(key, state, ended, SYSTEM_ACTOR)
        self._forget(key)

    async def tick(self) -> None:
        """Advance every recording conversation, and ping its screens on schedule.

        Concurrently, so one conversation's slow store or Studio read never
        delays another's liveness check.
        """
        keys = await self._store.recording_sessions()
        await asyncio.gather(*(self._tick_guarded(key) for key in keys))

    async def _tick_guarded(self, key: TenantSessionKey) -> None:
        try:
            await self._tick_one(key)
        except Exception as error:  # One conversation must not stall the others.
            logger.error("recording_tick_failed error=%s", type(error).__name__)

    async def _tick_one(self, key: TenantSessionKey) -> None:
        peeked = await self._store.load(key)
        ready = self._storage_ready(key)
        if peeked.phase is Phase.PAUSED and peeked.reason is Reason.POLICY:
            ready = ready and await self._policy_reread(key)
        if self._watched(key):
            # A state outlives its 24 h only while a screen is still there.
            await self._store.touch(key)
        async with self._locks.hold(key):
            state = await self._store.load(key)
            advanced = rs.advance(state, now=self._clock(), live=self.live(key), ready=ready)
            if advanced.phase is Phase.OFF and state.phase is Phase.OFF:
                await self._store.save(key, state)  # drops a stale index entry
            elif advanced != state:
                await self._commit(key, state, advanced, SYSTEM_ACTOR)
        if advanced.recording:
            await self._ping_when_due(key)
        else:
            self._forget(key)

    def _watched(self, key: TenantSessionKey) -> bool:
        return any(self._announcer.connected(key, role) for role in _ROLES)

    async def _policy_reread(self, key: TenantSessionKey) -> bool:
        """A paused-for-policy conversation asks Studio again, at most every 5 s."""
        now = self._monotonic()
        if now - self._last_policy_read.get(key, float("-inf")) < rs.PING_INTERVAL_SECONDS:
            return False
        self._last_policy_read[key] = now
        try:
            policy = await asyncio.wait_for(self._policy(key.tenant_id), POLICY_READ_SECONDS)
        except Exception:
            return False
        return policy is not None and policy.enabled

    async def _ping_when_due(self, key: TenantSessionKey, *, now: float | None = None) -> None:
        now = self._monotonic() if now is None else now
        if now - self._last_ping.get(key, float("-inf")) < rs.PING_INTERVAL_SECONDS:
            return
        self._last_ping[key] = now
        await self._announcer.broadcast(key, recording_ping_frame(key.session_id), None)

    def _forget(self, key: TenantSessionKey) -> None:
        self._last_ping.pop(key, None)
        self._last_policy_read.pop(key, None)
        for role in _ROLES:
            self._pongs.pop((key, role), None)

    async def _change(
        self,
        key: TenantSessionKey,
        actor: str,
        transition: Callable[[RecordingState, datetime], RecordingState],
    ) -> RecordingState:
        async with self._locks.hold(key):
            state = await self._store.load(key)
            changed = transition(state, self._clock())
            if changed != state:
                await self._commit(key, state, changed, actor)
        return changed

    async def _commit(
        self, key: TenantSessionKey, before: RecordingState, after: RecordingState, actor: str
    ) -> None:
        await self._store.save(key, after)
        if after.state_version == before.state_version:
            return  # an acknowledgement: nothing for the screens to render
        await self._announcer.broadcast(key, self._state_frame(key, after), None)
        if after.phase is Phase.ASKING:
            await self._announcer.broadcast(
                key, self._request_frame(key, after), ClientType.CUSTOMER
            )
        if after.phase in (Phase.ARMING, Phase.ON):
            # ARMING needs pongs before it can turn ON, and a screen shows ON as
            # live only once a ping arrives: both get one now, not in up to 5 s.
            self._last_ping.pop(key, None)
            await self._ping_when_due(key)
        await self._record(key, before, after, actor)

    async def _record(
        self, key: TenantSessionKey, before: RecordingState, after: RecordingState, actor: str
    ) -> None:
        """Audit the transition. A failed write is logged; the transition already happened."""
        event_type = f"recording.{after.phase.value}"
        if after.reason is not None:
            event_type += f".{after.reason.value}"
        event = AuditEvent(
            tenant_id=key.tenant_id,
            actor_sub=actor,
            event_type=event_type,
            # The window a stop closes, which the OFF state no longer names.
            object_ref=after.window_id or before.window_id or after.request_id or "",
            at=self._clock(),
        )
        try:
            await self._audit(event)
        except Exception as error:
            logger.error(
                "recording_audit_failed tenant_ref=%s event=%s error=%s",
                key.tenant_ref,
                event_type,
                type(error).__name__,
            )

    @staticmethod
    def _state_frame(key: TenantSessionKey, state: RecordingState) -> Any:
        return recording_state_frame(
            key.session_id,
            state=state.phase.value,
            reason=state.reason.value if state.reason else None,
            window_id=state.window_id,
            state_version=state.state_version,
            since=state.since,
        )

    @staticmethod
    def _request_frame(key: TenantSessionKey, state: RecordingState) -> Any:
        return recording_request_frame(
            key.session_id,
            request_id=state.request_id or "",
            consent_kind=state.request_kind or "first",
        )
