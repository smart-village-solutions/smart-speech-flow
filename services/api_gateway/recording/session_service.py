"""The gateway side of recording a live conversation (spec §5.1, §5.2, §14).

Holds each conversation's state under a per-session lock, announces every
transition to both screens, and runs the ping loop that keeps a recording
honest: while it is not OFF, both screens must answer within the liveness
window or ON turns PAUSED. The screens never decide the state; they only
acknowledge the version they render.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

from ..clock import utc_now
from ..keyed_locks import KeyedLocks
from ..realtime_protocol import (
    Frame,
    recording_error_frame,
    recording_ping_frame,
    recording_request_frame,
    recording_state_frame,
)
from ..session_models import ClientType
from ..session_pseudonym import SessionPseudonymizer
from ..studio_v2 import RecordingPolicy
from ..tenant_session import TenantSessionKey
from . import session_state as rs
from .archive_service import ArchiveUnavailableError, ConversationArchive, MessageArtefacts
from .audit import AuditEvent
from .consent_evidence import ConsentEvidenceError, GuestAnswer, evidence
from .consent_text import ConsentText, consent_text
from .consent_voice import ConsentVoice
from .records import PlaybackEvent
from .session_state import ConsentKind, Phase, Reason, RecordingState, Snapshot
from .session_store import RecordingStateStore

logger = logging.getLogger(__name__)

TICK_SECONDS: Final[float] = 1.0
# How long a tick waits for any one conversation; a slower one finishes on its own.
TICK_STEP_SECONDS: Final[float] = 2.0
# A policy read the tick waits for; a slower Studio leaves the pause in place.
POLICY_READ_SECONDS: Final[float] = 1.0
# The read at a message's acceptance while ON (§14); a slower Studio pauses recording.
ACCEPT_POLICY_READ_SECONDS: Final[float] = 2.0
# How long an archive step may hold the session lock: a slower database pauses recording.
ARCHIVE_SECONDS: Final[float] = 10.0
GUEST_ACTOR: Final[str] = "guest"
SYSTEM_ACTOR: Final[str] = "system"
_ROLES: Final[tuple[ClientType, ClientType]] = (ClientType.ADMIN, ClientType.CUSTOMER)

PolicyReader = Callable[[str], Awaitable[RecordingPolicy | None]]
Send = Callable[[Frame], Awaitable[None]]
Opening = Callable[[RecordingState, RecordingState], Awaitable[RecordingState]]


class RecordingUnavailableError(Exception):
    """Recording cannot start for this conversation; `code` is the wire error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ServedConsent:
    """The open question as the guest's screen shows it (§6)."""

    request_id: str
    kind: ConsentKind
    text: ConsentText
    # What a first yes asks beyond the text; a resume asks for neither.
    signature: str
    proposed_name: str | None


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
        archive: ConversationArchive | None = None,
        storage_ready: Callable[[TenantSessionKey], bool] | None = None,
        pseudonymizer: SessionPseudonymizer | None = None,
        clock: Callable[[], datetime] = utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store = store
        self._announcer = announcer
        self._policy = policy
        self._recovery_key_ready = recovery_key_ready
        self._audit = audit
        self._archive = archive
        if storage_ready is None:
            storage_ready = archive.ready if archive is not None else (lambda _key: True)
        self._storage_ready = storage_ready
        # Told of every recorded session, so its telemetry goes unlinkable (§5.5).
        self._pseudonymizer = pseudonymizer
        self._clock = clock
        self._monotonic = monotonic
        self._locks: KeyedLocks[TenantSessionKey] = KeyedLocks()
        self._pongs: dict[tuple[TenantSessionKey, ClientType], float] = {}
        self._last_ping: dict[TenantSessionKey, float] = {}
        self._last_policy_read: dict[TenantSessionKey, float] = {}
        # A conversation whose last tick step is still running is not started again.
        self._ticking: dict[TenantSessionKey, asyncio.Task[None]] = {}
        # Reads the open question's text aloud for the guest (§6).
        self.voice = ConsentVoice()
        # The text last served to each guest and its request: a "no" to a resume cites it.
        self._served: dict[TenantSessionKey, tuple[str, ConsentText]] = {}

    async def state(self, key: TenantSessionKey) -> RecordingState:
        return await self._store.load(key)

    async def check_available(self, tenant_id: str) -> RecordingPolicy:
        """The tenant's policy, unless it may not record now: a live, fail-closed read (§14)."""
        if self._archive is None or not self._archive.can_record(tenant_id):
            raise RecordingUnavailableError("ARCHIVE_UNAVAILABLE")
        try:
            policy = await self._policy(tenant_id)
        except Exception:
            raise RecordingUnavailableError("RECORDING_POLICY_UNAVAILABLE") from None
        if policy is None or not policy.enabled:
            raise RecordingUnavailableError("RECORDING_DISABLED")
        if not await self._recovery_key_ready(tenant_id):
            raise RecordingUnavailableError("RECOVERY_KEY_MISSING")
        return policy

    async def request(
        self,
        key: TenantSessionKey,
        *,
        request_id: str,
        requested_by: str,
        proposed_name: str | None = None,
        id_checked: bool = False,
    ) -> RecordingState:
        current = await self._store.load(key)
        if current.request_id == request_id:
            return current  # a replay: the checks were made when it was new
        self._require_guest(key)
        policy = await self.check_available(key.tenant_id)
        id_checked = id_checked and policy.id_check != "off"

        def transition(state: RecordingState, now: datetime) -> RecordingState:
            # Again under the lock: the guest may have left, or the session ended,
            # while the policy was read.
            self._require_guest(key)
            first = state.phase is Phase.OFF and not state.consented
            if first and policy.id_check == "required" and not id_checked:
                raise ConsentEvidenceError("ID_CHECK_REQUIRED")
            return rs.request(
                state,
                request_id=request_id,
                requested_by=requested_by,
                now=now,
                proposed_name=proposed_name,
                id_checked=id_checked,
            )

        return await self._change(key, requested_by, transition)

    async def consent(self, key: TenantSessionKey, language: str) -> ServedConsent:
        """The open question's text in the guest's language, from a live policy read."""
        state = await self._store.load(key)
        if state.phase is not Phase.ASKING or state.request_id is None:
            raise rs.RecordingConflictError("RECORDING_REQUEST_STALE")
        policy = await self.check_available(key.tenant_id)
        kind = state.request_kind or "first"
        text = consent_text(policy, language, kind)
        self._served[key] = (state.request_id, text)
        first = kind == "first"
        return ServedConsent(
            request_id=state.request_id,
            kind=kind,
            text=text,
            signature=policy.signature if first else "off",
            proposed_name=state.proposed_name if first else None,
        )

    def _require_guest(self, key: TenantSessionKey) -> None:
        if not self._announcer.connected(key, ClientType.CUSTOMER):
            raise RecordingUnavailableError("GUEST_NOT_CONNECTED")

    async def cancel(self, key: TenantSessionKey, *, request_id: str, actor: str) -> RecordingState:
        return await self._change(
            key, actor, lambda state, now: rs.cancel(state, request_id=request_id, now=now)
        )

    async def answer(
        self,
        key: TenantSessionKey,
        *,
        request_id: str,
        consent: bool,
        reply: GuestAnswer | None = None,
    ) -> RecordingState:
        """The guest's answer. A yes must carry the evidence §6 asks; a no never needs any."""
        current = await self._store.load(key)
        policy = None
        fields: dict[str, Any] = {}
        if consent and current.phase is Phase.ASKING and current.request_id == request_id:
            # The policy is read again at the guest's yes; a failure refuses it.
            # A replay or a stale answer needs no read: the transition settles it.
            policy = await self.check_available(key.tenant_id)
            fields = evidence(policy, current, reply or GuestAnswer(language=""))
        window_id = str(uuid.uuid4())
        return await self._change(
            key,
            GUEST_ACTOR,
            lambda state, now: rs.answer(
                state, request_id=request_id, consent=consent, window_id=window_id, now=now
            ),
            opening=self._opening(key, policy, fields),
        )

    def _opening(
        self, key: TenantSessionKey, policy: RecordingPolicy | None, fields: dict[str, Any]
    ) -> Opening:
        """The yes's archive work, inside the lock: if it fails, the yes did not happen."""

        async def open_window(before: RecordingState, after: RecordingState) -> RecordingState:
            if self._archive is None:
                raise RecordingUnavailableError("ARCHIVE_UNAVAILABLE")
            if policy is None:
                raise RecordingUnavailableError("RECORDING_POLICY_UNAVAILABLE")
            try:
                return await asyncio.wait_for(
                    self._archive.open_window(key, before, after, policy, fields),
                    ARCHIVE_SECONDS,
                )
            except (ArchiveUnavailableError, TimeoutError) as error:
                code = getattr(error, "code", "timeout")
                logger.error(
                    "recording_window_not_opened tenant_ref=%s code=%s", key.tenant_ref, code
                )
                # The question stays open for the guest; the employee should know why.
                await self._announcer.broadcast(
                    key,
                    recording_error_frame(key.session_id, code="ARCHIVE_WRITE_FAILED"),
                    ClientType.ADMIN,
                )
                raise RecordingUnavailableError("ARCHIVE_WRITE_FAILED") from None

        return open_window

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

    async def accept(self, key: TenantSessionKey) -> Snapshot:
        """A message's acceptance (§5.3): the state under the lock, after the §14 policy read.

        The read happens under the lock, for the very state the message is accepted
        in; it is bounded, so the lock is held at most that long.
        """
        async with self._locks.hold(key):
            state = await self._store.load(key)
            # After a restart the process learns it here, before the message's telemetry.
            self._note_recorded(key, state)
            if state.phase is Phase.ON and not await self._policy_allows(key.tenant_id):
                paused = rs.pause(state, reason=Reason.POLICY, now=self._clock())
                await self._commit(key, state, paused, SYSTEM_ACTOR)
                state = paused
            return rs.snapshot(state, live=self.live(key))

    async def _policy_allows(self, tenant_id: str) -> bool:
        try:
            policy = await asyncio.wait_for(self._policy(tenant_id), ACCEPT_POLICY_READ_SECONDS)
        except Exception:
            return False
        return policy is not None and policy.enabled

    async def archive(
        self, key: TenantSessionKey, accepted: Snapshot, artefacts: MessageArtefacts
    ) -> str | None:
        """A message's completion (§5.3): decide and append in one locked step.

        Returns the chain entry, or None when the message is not stored. Delivery
        never waits on why: a failed archive pauses recording with reason
        `storage`, which both screens show, and the message goes out as usual.
        """
        if self._archive is None or not accepted.holds():
            return None
        async with self._locks.hold(key):
            state = await self._store.load(key)
            if not rs.archivable(accepted, rs.snapshot(state, live=self.live(key))):
                return None
            try:
                return await asyncio.wait_for(
                    self._archive.archive_message(key, state, artefacts), ARCHIVE_SECONDS
                )
            except Exception as error:  # an archive fault must never cost the message
                await self._archive_failed(key, state, error)
                return None

    async def playback(
        self,
        key: TenantSessionKey,
        role: ClientType,
        message_id: str,
        event: PlaybackEvent,
    ) -> None:
        """A screen played an archived message: its own entry, if recording holds now (§7.1)."""
        if self._archive is None:
            return
        async with self._locks.hold(key):
            state = await self._store.load(key)
            if not rs.snapshot(state, live=self.live(key)).holds():
                return
            try:
                await asyncio.wait_for(
                    self._archive.archive_playback(key, state, message_id, event, role),
                    ARCHIVE_SECONDS,
                )
            except Exception as error:  # a report is never worth an error to the screen
                await self._archive_failed(key, state, error)

    async def _archive_failed(
        self, key: TenantSessionKey, state: RecordingState, error: Exception
    ) -> None:
        """Under the lock. Recording pauses until the archive can take entries again."""
        code = error.code if isinstance(error, ArchiveUnavailableError) else type(error).__name__
        logger.error("recording_archive_failed tenant_ref=%s code=%s", key.tenant_ref, code)
        paused = rs.pause(state, reason=Reason.STORAGE, now=self._clock())
        if paused != state:
            await self._commit(key, state, paused, SYSTEM_ACTOR)

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
        self._note_recorded(key, state)
        await send(self._state_frame(key, state))
        if role is ClientType.CUSTOMER and state.phase is Phase.ASKING:
            await send(self._request_frame(key, state))
        if state.recording:
            # Its band counts as live only after a ping; the next might be 5 s away.
            await send(recording_ping_frame(key.session_id))

    async def note_recorded(self, key: TenantSessionKey) -> None:
        """Mark the session as recorded if its state says so: a restart forgot it."""
        self._note_recorded(key, await self._store.load(key))

    async def session_ended(self, key: TenantSessionKey) -> None:
        try:
            await self._end(key)
        finally:
            self._served.pop(key, None)
            if self._pseudonymizer is not None:
                # Its termination event was emitted when the record committed.
                self._pseudonymizer.ended(key.session_id)
            self._forget(key)

    async def _end(self, key: TenantSessionKey) -> None:
        async with self._locks.hold(key):
            state = await self._store.load(key)
            ended = rs.end(state, now=self._clock())
            if ended != state:
                await self._store.save(key, ended)
                await self._record(key, state, ended, SYSTEM_ACTOR)
            if self._archive is not None:
                await self._archive.transitioned(key, state, ended)
                await self._archive.session_ended(key, state)

    async def tick(self) -> None:
        """Advance every recording conversation, and ping its screens on schedule.

        Concurrently, so one conversation's slow store, Studio read or database
        write never delays another's liveness check: a step still running after
        TICK_STEP_SECONDS keeps running, and its conversation sits out the next ticks.
        """
        keys = await self._store.recording_sessions()
        started = []
        for key in keys:
            if key in self._ticking:
                continue
            task = asyncio.create_task(self._tick_guarded(key))
            self._ticking[key] = task
            task.add_done_callback(functools.partial(self._tick_done, key))
            started.append(task)
        if started:
            await asyncio.wait(started, timeout=TICK_STEP_SECONDS)

    def _tick_done(self, key: TenantSessionKey, _task: asyncio.Task[None]) -> None:
        self._ticking.pop(key, None)

    async def close(self) -> None:
        """Cancel tick steps still running, so none outlives the gateway's shutdown."""
        steps = list(self._ticking.values())
        for step in steps:
            step.cancel()
        await asyncio.gather(*steps, return_exceptions=True)

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
        *,
        opening: Opening | None = None,
    ) -> RecordingState:
        async with self._locks.hold(key):
            state = await self._store.load(key)
            changed = transition(state, self._clock())
            audited = False
            if (
                opening is not None
                and state.phase is Phase.ASKING
                and changed.phase is Phase.ARMING
            ):
                # The archive writes this transition's audit event with the consent entry.
                changed, audited = await opening(state, changed), True
            if changed != state:
                await self._commit(key, state, changed, actor, audited=audited)
        return changed

    async def _commit(
        self,
        key: TenantSessionKey,
        before: RecordingState,
        after: RecordingState,
        actor: str,
        *,
        audited: bool = False,
    ) -> None:
        await self._store.save(key, after)
        self._note_recorded(key, after)
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
        if not audited:
            await self._record(key, before, after, actor)
        if self._archive is not None:
            served = self._served.get(key)
            text = served[1] if served is not None and served[0] == before.request_id else None
            await self._archive.transitioned(key, before, after, served=text)

    def _note_recorded(self, key: TenantSessionKey, state: RecordingState) -> None:
        if state.consented and self._pseudonymizer is not None:
            self._pseudonymizer.mark_recorded(key.session_id)

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
