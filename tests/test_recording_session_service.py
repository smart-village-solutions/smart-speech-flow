"""RecordingSessions: requests, answers, acknowledgements, liveness and pings (spec §5)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from services.api_gateway.recording import session_service
from services.api_gateway.recording.audit import AuditEvent
from services.api_gateway.recording.session_service import (
    RecordingSessions,
    RecordingUnavailableError,
)
from services.api_gateway.recording.session_state import (
    Phase,
    Reason,
    RecordingConflictError,
    RecordingState,
)
from services.api_gateway.recording.session_store import MemoryRecordingStateStore
from services.api_gateway.session_models import ClientType
from services.api_gateway.studio_v2 import RecordingPolicy
from services.api_gateway.tenant_session import TenantSessionKey
from tests.recording_archive_fakes import archive_rig

KEY = TenantSessionKey("tenant-kassel", "ABCD1234")
ADMIN, GUEST = ClientType.ADMIN, ClientType.CUSTOMER
POLICY_FIELDS = {
    "enabled": True,
    "legalBasis": "consent",
    "signature": "optional",
    "idCheck": "off",
    "retentionHours": 720,
    "verificationRequired": False,
    "recoveryMode": "standard",
    "timestampAuthorityUrl": "https://tsa.example.org/tsr",
    "auditRetentionHours": 8760,
}


class Announcer:
    def __init__(self) -> None:
        self.frames: list[tuple[dict[str, Any], ClientType | None]] = []
        self.guest_connected = True
        self.admin_connected = True

    async def broadcast(self, key, frame, role) -> None:
        if key == KEY:
            self.frames.append((dict(frame), role))

    def connected(self, key, role) -> bool:
        return self.admin_connected if role is ADMIN else self.guest_connected

    def types(self) -> list[str]:
        return [frame["type"] for frame, _ in self.frames]

    def states(self) -> list[str]:
        return [frame["state"] for frame, _ in self.frames if frame["type"] == "recording_state"]


class Clocks:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        self.mono = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)
        self.mono += seconds


class Harness:
    def __init__(self, root) -> None:
        self.announcer = Announcer()
        self.clocks = Clocks()
        self.rig = archive_rig(root, lambda: self.clocks.now)
        self.audit: list[AuditEvent] = []
        self.policy: RecordingPolicy | None = RecordingPolicy.model_validate(POLICY_FIELDS)
        self.policy_fails = False
        self.recovery_key = True
        self.storage_ok = True
        self.store = MemoryRecordingStateStore()
        self.service = RecordingSessions(
            store=self.store,
            announcer=self.announcer,
            policy=self._read_policy,
            recovery_key_ready=self._recovery_ready,
            audit=self._append,
            archive=self.rig.archive,
            storage_ready=lambda _key: self.storage_ok,
            clock=lambda: self.clocks.now,
            monotonic=lambda: self.clocks.mono,
        )

    async def _read_policy(self, tenant_id: str) -> RecordingPolicy | None:
        assert tenant_id == KEY.tenant_id
        if self.policy_fails:
            raise RuntimeError("studio down")
        return self.policy

    async def _recovery_ready(self, tenant_id: str) -> bool:
        return self.recovery_key

    async def _append(self, event: AuditEvent) -> None:
        self.audit.append(event)

    async def ack_both(self) -> None:
        version = (await self.service.state(KEY)).state_version
        await self.service.acknowledge(KEY, ADMIN, version)
        await self.service.acknowledge(KEY, GUEST, version)

    async def on(self) -> None:
        await self.service.request(KEY, request_id="r1", requested_by="emp-sub")
        await self.service.answer(KEY, request_id="r1", consent=True)
        await self.ack_both()
        await self.ack_both()


@pytest.fixture
def h(tmp_path) -> Harness:
    return Harness(tmp_path)


async def test_a_request_announces_asking_to_both_and_asks_only_the_guest(h) -> None:
    state = await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    assert state.phase is Phase.ASKING
    (announced, to_both), (asked, to_guest) = h.announcer.frames
    assert (announced["state"], announced["state_version"], to_both) == ("asking", 1, None)
    assert (asked["type"], asked["request_id"], asked["consent_kind"], to_guest) == (
        "recording_request",
        "r1",
        "first",
        GUEST,
    )
    assert [(e.actor_sub, e.event_type, e.object_ref) for e in h.audit] == [
        ("emp-sub", "recording.asking", "r1")
    ]


@pytest.mark.parametrize(
    "setup,code",
    [
        (lambda h: setattr(h, "policy_fails", True), "RECORDING_POLICY_UNAVAILABLE"),
        (lambda h: setattr(h, "policy", None), "RECORDING_DISABLED"),
        (
            lambda h: setattr(
                h, "policy", RecordingPolicy.model_validate(POLICY_FIELDS | {"enabled": False})
            ),
            "RECORDING_DISABLED",
        ),
        (lambda h: setattr(h, "recovery_key", False), "RECOVERY_KEY_MISSING"),
        (lambda h: setattr(h.announcer, "guest_connected", False), "GUEST_NOT_CONNECTED"),
    ],
)
async def test_a_request_fails_closed(h, setup, code) -> None:
    setup(h)
    with pytest.raises(RecordingUnavailableError) as refused:
        await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    assert refused.value.code == code
    assert (await h.service.state(KEY)).phase is Phase.OFF
    assert h.announcer.frames == []


async def test_a_yes_rereads_the_policy_and_a_failure_keeps_the_question_open(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    h.policy_fails = True
    with pytest.raises(RecordingUnavailableError):
        await h.service.answer(KEY, request_id="r1", consent=True)
    assert (await h.service.state(KEY)).phase is Phase.ASKING
    declined = await h.service.answer(KEY, request_id="r1", consent=False)
    assert (declined.phase, declined.reason) == (Phase.OFF, Reason.DECLINED)


async def test_a_yes_arms_and_pings_at_once_then_both_acks_and_pongs_turn_it_on(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    armed = await h.service.answer(KEY, request_id="r1", consent=True)
    assert armed.phase is Phase.ARMING and armed.window_id
    assert h.announcer.types()[-1] == "recording_ping"
    await h.service.acknowledge(KEY, ADMIN, armed.state_version)
    assert (await h.service.state(KEY)).phase is Phase.ARMING
    await h.service.acknowledge(KEY, GUEST, armed.state_version)
    turned = await h.service.state(KEY)
    assert (turned.phase, turned.window_id) == (Phase.ON, armed.window_id)
    assert h.announcer.states() == ["asking", "arming", "on"]
    assert not (await h.service.snapshot(KEY)).holds()
    await h.ack_both()
    assert (await h.service.snapshot(KEY)).holds()


async def test_lost_pongs_pause_within_the_liveness_window_and_resume_after_reacks(h) -> None:
    await h.on()
    h.clocks.advance(12)
    await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.ON
    h.clocks.advance(1)
    await h.service.tick()
    paused = await h.service.state(KEY)
    assert (paused.phase, paused.reason) == (Phase.PAUSED, Reason.LIVENESS)
    await h.ack_both()
    resumed = await h.service.state(KEY)
    assert (resumed.phase, resumed.window_id) == (Phase.ON, paused.window_id)


async def test_pongs_from_both_keep_it_on_and_pings_go_out_every_five_seconds(h) -> None:
    await h.on()
    pings = h.announcer.types().count("recording_ping")
    for _ in range(30):
        h.clocks.advance(1)
        h.service.pong(KEY, ADMIN)
        h.service.pong(KEY, GUEST)
        await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.ON
    assert h.announcer.types().count("recording_ping") - pings == 6


async def test_one_silent_screen_is_enough_to_pause(h) -> None:
    await h.on()
    for _ in range(13):
        h.clocks.advance(1)
        h.service.pong(KEY, ADMIN)
        await h.service.tick()
    assert (await h.service.state(KEY)).reason is Reason.LIVENESS


async def test_an_unacknowledged_arming_pauses_after_ten_seconds(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    await h.service.answer(KEY, request_id="r1", consent=True)
    h.clocks.advance(10)
    await h.service.tick()
    assert (await h.service.state(KEY)).reason is Reason.UNACKNOWLEDGED


async def test_an_unanswered_request_turns_off_after_two_minutes(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    h.clocks.advance(120)
    await h.service.tick()
    state = await h.service.state(KEY)
    assert (state.phase, state.reason) == (Phase.OFF, Reason.UNANSWERED)
    assert await h.store.recording_sessions() == []


async def test_a_policy_pause_resumes_only_once_the_policy_reads_again(h) -> None:
    await h.on()
    await h.service.pause(KEY, Reason.POLICY)
    await h.ack_both()
    h.policy_fails = True
    await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.PAUSED
    h.policy_fails = False
    await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.PAUSED  # read again only after 5 s
    h.clocks.advance(5)
    h.service.pong(KEY, ADMIN)
    h.service.pong(KEY, GUEST)
    await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.ON


async def test_a_storage_pause_waits_for_the_store(h) -> None:
    await h.on()
    h.storage_ok = False
    await h.service.pause(KEY, Reason.STORAGE)
    await h.ack_both()
    assert (await h.service.state(KEY)).phase is Phase.PAUSED
    h.storage_ok = True
    await h.service.tick()
    assert (await h.service.state(KEY)).phase is Phase.ON


async def test_stops_from_either_side_and_duplicates_announce_once(h) -> None:
    await h.on()
    frames = len(h.announcer.frames)
    await h.service.stop(KEY, role=GUEST, actor="guest")
    await h.service.stop(KEY, role=GUEST, actor="guest")
    await h.service.stop(KEY, role=ADMIN, actor="emp-sub")
    assert h.announcer.states()[-1] == "off"
    assert len(h.announcer.frames) == frames + 1
    assert h.audit[-1].event_type == "recording.off.stopped_by_guest"


async def test_conflicts_surface_as_errors(h) -> None:
    await h.on()
    with pytest.raises(RecordingConflictError):
        await h.service.request(KEY, request_id="r2", requested_by="emp-sub")


async def test_a_reconnecting_guest_learns_the_state_and_the_open_request(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    sent: list[dict[str, Any]] = []

    async def send(frame) -> None:
        sent.append(dict(frame))

    await h.service.greet(KEY, GUEST, send)
    await h.service.greet(KEY, ADMIN, send)
    assert [frame["type"] for frame in sent] == [
        "recording_state",
        "recording_request",
        "recording_state",
    ]


async def test_the_session_end_turns_off_without_a_frame_and_forgets_liveness(h) -> None:
    await h.on()
    frames = len(h.announcer.frames)
    await h.service.session_ended(KEY)
    state = await h.service.state(KEY)
    assert (state.phase, state.reason) == (Phase.OFF, Reason.SESSION_ENDED)
    assert len(h.announcer.frames) == frames
    assert not h.service.live(KEY)


async def test_a_failed_audit_write_does_not_undo_the_transition(h) -> None:
    async def broken(_event) -> None:
        raise RuntimeError("database down")

    h.service._audit = broken
    state = await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    assert state.phase is Phase.ASKING
    assert (await h.service.state(KEY)).phase is Phase.ASKING


async def test_one_failing_conversation_does_not_stall_the_others(h) -> None:
    broken = TenantSessionKey("tenant-kassel", "BROKEN12")
    await h.on()
    original_sessions, original_load = h.store.recording_sessions, h.store.load

    async def sessions():
        return [broken, *await original_sessions()]

    async def load(key):
        if key == broken:
            raise RuntimeError("redis hiccup")
        return await original_load(key)

    h.store.recording_sessions, h.store.load = sessions, load
    h.clocks.advance(13)
    await h.service.tick()
    assert (await h.service.state(KEY)).reason is Reason.LIVENESS


async def test_a_reconnecting_screen_is_pinged_with_its_greeting(h) -> None:
    """Its band shows live only after a ping; without one it read "paused" while stored."""
    await h.on()
    sent: list[dict[str, Any]] = []

    async def send(frame) -> None:
        sent.append(dict(frame))

    await h.service.greet(KEY, GUEST, send)
    assert [frame["type"] for frame in sent] == ["recording_state", "recording_ping"]
    await h.service.stop(KEY, role=ADMIN, actor="emp-sub")
    sent.clear()
    await h.service.greet(KEY, GUEST, send)
    assert [frame["type"] for frame in sent] == ["recording_state"]


async def test_turning_on_pings_both_screens_at_once(h) -> None:
    await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    await h.service.answer(KEY, request_id="r1", consent=True)
    h.clocks.advance(1)
    await h.ack_both()
    types = h.announcer.types()
    assert types[-2:] == ["recording_state", "recording_ping"]
    assert h.announcer.states()[-1] == "on"


async def test_a_closed_screen_stops_holding_at_once(h) -> None:
    await h.on()
    assert (await h.service.snapshot(KEY)).holds()
    h.service.released(KEY, GUEST)  # another guest socket is still open
    assert (await h.service.snapshot(KEY)).holds()
    h.announcer.guest_connected = False
    h.service.released(KEY, GUEST)
    assert not (await h.service.snapshot(KEY)).holds()
    await h.service.tick()
    assert (await h.service.state(KEY)).reason is Reason.LIVENESS


async def test_a_hanging_policy_read_holds_back_no_other_conversation(h) -> None:
    other = TenantSessionKey("tenant-kassel", "OTHER123")
    await h.on()
    await h.service.pause(KEY, Reason.POLICY)
    await h.ack_both()
    await h.store.save(
        other, RecordingState(phase=Phase.ASKING, state_version=1, since=h.clocks.now)
    )
    # Three conversations waiting on Studio: one after the other they would take 3 s.
    paused = await h.service.state(KEY)
    for session_id in ("SLOW0001", "SLOW0002"):
        await h.store.save(TenantSessionKey("tenant-kassel", session_id), paused)
    hang = asyncio.Event()

    async def hanging(_tenant_id):
        await hang.wait()

    h.service._policy = hanging
    h.clocks.advance(120)
    await asyncio.wait_for(h.service.tick(), timeout=2)
    assert (await h.service.state(other)).reason is Reason.UNANSWERED
    assert (await h.service.state(KEY)).phase is Phase.PAUSED


async def test_a_policy_pause_rereads_studio_at_most_every_five_seconds(h) -> None:
    await h.on()
    await h.service.pause(KEY, Reason.POLICY)
    await h.ack_both()
    reads = 0

    async def failing(_tenant_id):
        nonlocal reads
        reads += 1
        raise RuntimeError("studio down")

    h.service._policy = failing
    for _ in range(11):
        h.service.pong(KEY, ADMIN)
        h.service.pong(KEY, GUEST)
        await h.service.tick()
        h.clocks.advance(1)
    assert reads == 3


async def test_a_request_racing_the_guests_departure_is_refused(h) -> None:
    async def policy_while_guest_leaves(_tenant_id):
        h.announcer.guest_connected = False
        return h.policy

    h.service._policy = policy_while_guest_leaves
    with pytest.raises(RecordingUnavailableError) as refused:
        await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    assert refused.value.code == "GUEST_NOT_CONNECTED"
    assert (await h.service.state(KEY)).phase is Phase.OFF


async def test_replays_return_the_state_without_rechecking(h) -> None:
    asked = await h.service.request(KEY, request_id="r1", requested_by="emp-sub")
    armed = await h.service.answer(KEY, request_id="r1", consent=True)
    h.announcer.guest_connected = False
    h.policy_fails = True
    assert await h.service.request(KEY, request_id="r1", requested_by="emp-sub") == armed
    assert await h.service.answer(KEY, request_id="r1", consent=True) == armed
    with pytest.raises(RecordingConflictError) as stale:
        await h.service.answer(KEY, request_id="r0", consent=True)
    assert stale.value.code == "RECORDING_REQUEST_STALE"
    assert asked.request_id == "r1"


async def test_the_event_closing_a_window_names_that_window(h) -> None:
    await h.on()
    window = (await h.service.state(KEY)).window_id
    await h.service.stop(KEY, role=GUEST, actor="guest")
    assert (h.audit[-1].event_type, h.audit[-1].object_ref) == (
        "recording.off.stopped_by_guest",
        window,
    )


async def test_the_tick_keeps_a_watched_state_from_expiring(h) -> None:
    touched: list[TenantSessionKey] = []

    async def touch(key) -> None:
        touched.append(key)

    h.store.touch = touch
    await h.on()
    await h.service.tick()
    h.announcer.guest_connected = False
    h.announcer.admin_connected = False
    await h.service.tick()
    assert touched == [KEY]


async def test_one_conversation_stuck_in_its_tick_holds_up_no_other(h, monkeypatch) -> None:
    other = TenantSessionKey(KEY.tenant_id, "OTHER123")
    stuck, seen = asyncio.Event(), []
    monkeypatch.setattr(session_service, "TICK_STEP_SECONDS", 0.1)

    async def recording_sessions():
        return [KEY, other]

    async def tick_one(key):
        seen.append(key)
        if key == KEY:
            await stuck.wait()

    monkeypatch.setattr(h.store, "recording_sessions", recording_sessions)
    monkeypatch.setattr(h.service, "_tick_one", tick_one)

    await asyncio.wait_for(h.service.tick(), 2)
    await asyncio.wait_for(h.service.tick(), 2)

    # The stuck one is not started again while its last step still waits.
    assert seen == [KEY, other, other]
    await h.service.close()
    assert h.service._ticking == {}
