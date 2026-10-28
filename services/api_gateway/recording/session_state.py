"""The recording state of one conversation, and every transition it may take (spec §5.1).

Pure: `RecordingSessions` holds the state under a per-session lock, stores it
and announces it; this module only decides. `state_version` counts
transitions, never acknowledgements, and a message is archived only while
both screens have acknowledged the current version and answer pings (§5.3).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Final, Literal

from ..session_models import ClientType

ASK_TIMEOUT: Final[timedelta] = timedelta(minutes=2)
# How long both screens have to acknowledge an ARMING or ON before it pauses.
ACK_TIMEOUT: Final[timedelta] = timedelta(seconds=10)
PING_INTERVAL_SECONDS: Final[float] = 5.0
LIVENESS_SECONDS: Final[float] = 12.0

ConsentKind = Literal["first", "resume"]


class Phase(str, Enum):
    OFF = "off"
    ASKING = "asking"
    ARMING = "arming"
    ON = "on"
    PAUSED = "paused"


class Reason(str, Enum):
    """Why the conversation is OFF or PAUSED; shown to both screens."""

    DECLINED = "declined"
    CANCELLED = "cancelled"
    UNANSWERED = "unanswered"
    STOPPED_BY_GUEST = "stopped_by_guest"
    STOPPED_BY_EMPLOYEE = "stopped_by_employee"
    SESSION_ENDED = "session_ended"
    LIVENESS = "liveness"
    UNACKNOWLEDGED = "unacknowledged"
    STORAGE = "storage"
    POLICY = "policy"


_STOPPED_BY: Final[dict[ClientType, Reason]] = {
    ClientType.ADMIN: Reason.STOPPED_BY_EMPLOYEE,
    ClientType.CUSTOMER: Reason.STOPPED_BY_GUEST,
}
_RECORDING: Final[frozenset[Phase]] = frozenset({Phase.ARMING, Phase.ON, Phase.PAUSED})


class RecordingConflictError(Exception):
    """The request does not fit the current state; `code` is the wire error code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class RecordingState:
    phase: Phase = Phase.OFF
    state_version: int = 0
    reason: Reason | None = None
    since: datetime | None = None
    window_id: str | None = None
    # The latest request, kept after it concludes so a replay changes nothing.
    request_id: str | None = None
    request_kind: ConsentKind | None = None
    requested_by: str | None = None
    answer: bool | None = None
    # Any yes in this conversation makes the next request a resume (§6).
    consented: bool = False
    acked_admin: int = 0
    acked_customer: int = 0
    # Set by the archive at the first yes and kept for the rest of the session,
    # so a restart continues the same archived conversation.
    conversation_id: str | None = None
    # A first request's extras, kept only while the guest is asked (§6).
    proposed_name: str | None = None
    id_checked_at: datetime | None = None

    @property
    def recording(self) -> bool:
        """ARMING, ON or PAUSED: pings run and both screens must stay live."""
        return self.phase in _RECORDING

    def acked_by_both(self) -> bool:
        return self.acked_admin == self.acked_customer == self.state_version


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What §5.3 compares at a message's acceptance and at its completion."""

    phase: Phase
    state_version: int
    acked_admin: int
    acked_customer: int
    window_id: str | None
    live: bool

    def holds(self) -> bool:
        return (
            self.phase is Phase.ON
            and self.acked_admin == self.acked_customer == self.state_version
            and self.live
        )


def snapshot(state: RecordingState, *, live: bool) -> Snapshot:
    return Snapshot(
        state.phase,
        state.state_version,
        state.acked_admin,
        state.acked_customer,
        state.window_id,
        live,
    )


def archivable(at_acceptance: Snapshot, at_completion: Snapshot) -> bool:
    """A message is stored only if recording held, unchanged, at both points."""
    return (
        at_acceptance.holds()
        and at_completion.holds()
        and at_acceptance.state_version == at_completion.state_version
        # The version restarts if the state itself is ever lost; the window does not.
        and at_acceptance.window_id == at_completion.window_id
    )


def _move(state: RecordingState, phase: Phase, now: datetime, **changes: object) -> RecordingState:
    """Every transition bumps the version, so earlier acknowledgements go stale."""
    changes.setdefault("reason", None)
    return replace(
        state,
        phase=phase,
        state_version=state.state_version + 1,
        since=now,
        **changes,  # type: ignore[arg-type]
    )


def _off(state: RecordingState, reason: Reason, now: datetime) -> RecordingState:
    return _move(
        state, Phase.OFF, now, reason=reason, window_id=None, proposed_name=None, id_checked_at=None
    )


def request(
    state: RecordingState,
    *,
    request_id: str,
    requested_by: str,
    now: datetime,
    proposed_name: str | None = None,
    id_checked: bool = False,
) -> RecordingState:
    """Ask the guest. A name and ID check belong to a first request only."""
    if state.request_id == request_id:
        return state
    if state.phase is not Phase.OFF:
        raise RecordingConflictError("RECORDING_BUSY")
    first = not state.consented
    return _move(
        state,
        Phase.ASKING,
        now,
        request_id=request_id,
        request_kind="first" if first else "resume",
        requested_by=requested_by,
        answer=None,
        proposed_name=proposed_name if first else None,
        id_checked_at=now if first and id_checked else None,
    )


def cancel(state: RecordingState, *, request_id: str, now: datetime) -> RecordingState:
    if state.phase is not Phase.ASKING or state.request_id != request_id:
        return state
    return _off(state, Reason.CANCELLED, now)


def answer(
    state: RecordingState, *, request_id: str, consent: bool, window_id: str, now: datetime
) -> RecordingState:
    if state.request_id != request_id:
        raise RecordingConflictError("RECORDING_REQUEST_STALE")
    if state.phase is not Phase.ASKING:
        if state.answer is consent:
            return state
        raise RecordingConflictError("RECORDING_REQUEST_STALE")
    if not consent:
        return replace(_off(state, Reason.DECLINED, now), answer=False)
    return _move(
        state,
        Phase.ARMING,
        now,
        window_id=window_id,
        answer=True,
        consented=True,
        proposed_name=None,
        id_checked_at=None,
    )


def stop(state: RecordingState, *, by: ClientType, now: datetime) -> RecordingState:
    if state.phase is Phase.OFF:
        return state
    if state.phase is Phase.ASKING:
        if by is ClientType.CUSTOMER:
            return replace(_off(state, Reason.DECLINED, now), answer=False)
        return _off(state, Reason.CANCELLED, now)
    return _off(state, _STOPPED_BY[by], now)


def end(state: RecordingState, *, now: datetime) -> RecordingState:
    if state.phase is Phase.OFF:
        return state
    return _off(state, Reason.SESSION_ENDED, now)


def pause(state: RecordingState, *, reason: Reason, now: datetime) -> RecordingState:
    if state.phase not in (Phase.ARMING, Phase.ON):
        return state
    return _move(state, Phase.PAUSED, now, reason=reason)


def acknowledge(state: RecordingState, *, role: ClientType, version: int) -> RecordingState:
    """Record that a screen renders `version`; a stale version changes nothing."""
    if version != state.state_version:
        return state
    if role is ClientType.ADMIN:
        return replace(state, acked_admin=version)
    return replace(state, acked_customer=version)


def advance(state: RecordingState, *, now: datetime, live: bool, ready: bool) -> RecordingState:
    """The transitions time and acknowledgements drive.

    `live`: both screens answered a ping within the liveness window.
    `ready`: no storage or policy problem remains (always true for the
    other pause reasons).
    """
    since = state.since or now
    if state.phase is Phase.ASKING and now - since >= ASK_TIMEOUT:
        return _off(state, Reason.UNANSWERED, now)
    if state.phase is Phase.ARMING:
        if state.acked_by_both() and live:
            return _move(state, Phase.ON, now)
        if now - since >= ACK_TIMEOUT:
            return _move(state, Phase.PAUSED, now, reason=Reason.UNACKNOWLEDGED)
        return state
    if state.phase is Phase.ON:
        if not live:
            return _move(state, Phase.PAUSED, now, reason=Reason.LIVENESS)
        # A lost acknowledgement would otherwise show "recording" while nothing is stored.
        if not state.acked_by_both() and now - since >= ACK_TIMEOUT:
            return _move(state, Phase.PAUSED, now, reason=Reason.UNACKNOWLEDGED)
        return state
    if state.phase is Phase.PAUSED and state.acked_by_both() and live and ready:
        return _move(state, Phase.ON, now)
    return state
