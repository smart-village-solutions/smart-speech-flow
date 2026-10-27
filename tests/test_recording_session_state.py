"""The recording state machine of spec §5.1 and the archive rule of §5.3."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from services.api_gateway.recording import session_state as rs
from services.api_gateway.recording.session_state import Phase, Reason, RecordingState
from services.api_gateway.session_models import ClientType

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def asking() -> RecordingState:
    return rs.request(RecordingState(), request_id="r1", requested_by="emp", now=T0)


def arming() -> RecordingState:
    return rs.answer(asking(), request_id="r1", consent=True, window_id="w1", now=T0)


def acked(state: RecordingState) -> RecordingState:
    state = rs.acknowledge(state, role=ClientType.ADMIN, version=state.state_version)
    return rs.acknowledge(state, role=ClientType.CUSTOMER, version=state.state_version)


def on() -> RecordingState:
    return rs.advance(acked(arming()), now=T0, live=True, ready=True)


def test_a_request_asks_the_guest_and_a_yes_arms_a_new_window() -> None:
    state = asking()
    assert (state.phase, state.state_version, state.request_kind) == (Phase.ASKING, 1, "first")
    state = arming()
    assert (state.phase, state.window_id, state.consented) == (Phase.ARMING, "w1", True)


def test_arming_turns_on_only_when_both_screens_acknowledged_and_are_live() -> None:
    state = arming()
    assert rs.advance(state, now=T0, live=True, ready=True).phase is Phase.ARMING
    one = rs.acknowledge(state, role=ClientType.ADMIN, version=state.state_version)
    assert rs.advance(one, now=T0, live=True, ready=True).phase is Phase.ARMING
    assert rs.advance(acked(state), now=T0, live=False, ready=True).phase is Phase.ARMING
    turned = rs.advance(acked(state), now=T0, live=True, ready=True)
    assert (turned.phase, turned.state_version) == (Phase.ON, state.state_version + 1)
    assert not turned.acked_by_both()


def test_a_missing_acknowledgement_pauses_after_ten_seconds() -> None:
    later = T0 + rs.ACK_TIMEOUT
    paused = rs.advance(arming(), now=later, live=True, ready=True)
    assert (paused.phase, paused.reason) == (Phase.PAUSED, Reason.UNACKNOWLEDGED)
    assert rs.advance(arming(), now=later - timedelta(seconds=1), live=True, ready=True).phase is (
        Phase.ARMING
    )


def test_lost_liveness_pauses_and_both_acks_resume_the_same_window() -> None:
    paused = rs.advance(on(), now=T0, live=False, ready=True)
    assert (paused.phase, paused.reason, paused.window_id) == (Phase.PAUSED, Reason.LIVENESS, "w1")
    assert rs.advance(paused, now=T0, live=True, ready=True).phase is Phase.PAUSED
    assert rs.advance(acked(paused), now=T0, live=False, ready=True).phase is Phase.PAUSED
    assert rs.advance(acked(paused), now=T0, live=True, ready=False).phase is Phase.PAUSED
    resumed = rs.advance(acked(paused), now=T0, live=True, ready=True)
    assert (resumed.phase, resumed.window_id) == (Phase.ON, "w1")


def test_an_unanswered_request_lapses_after_two_minutes() -> None:
    lapsed = rs.advance(asking(), now=T0 + rs.ASK_TIMEOUT, live=False, ready=True)
    assert (lapsed.phase, lapsed.reason) == (Phase.OFF, Reason.UNANSWERED)


def test_no_declines_cancel_cancels_and_both_leave_no_window() -> None:
    declined = rs.answer(asking(), request_id="r1", consent=False, window_id="w1", now=T0)
    assert (declined.phase, declined.reason, declined.consented) == (
        Phase.OFF,
        Reason.DECLINED,
        False,
    )
    cancelled = rs.cancel(asking(), request_id="r1", now=T0)
    assert (cancelled.phase, cancelled.reason) == (Phase.OFF, Reason.CANCELLED)
    assert rs.cancel(asking(), request_id="other", now=T0) == asking()


@pytest.mark.parametrize(
    "by,reason",
    [
        (ClientType.ADMIN, Reason.STOPPED_BY_EMPLOYEE),
        (ClientType.CUSTOMER, Reason.STOPPED_BY_GUEST),
    ],
)
def test_either_side_stops_and_the_window_closes(by, reason) -> None:
    for state in (arming(), on(), rs.pause(on(), reason=Reason.STORAGE, now=T0)):
        stopped = rs.stop(state, by=by, now=T0)
        assert (stopped.phase, stopped.reason, stopped.window_id) == (Phase.OFF, reason, None)


def test_a_stop_while_asking_is_the_guests_no_or_the_employees_cancel() -> None:
    assert rs.stop(asking(), by=ClientType.CUSTOMER, now=T0).reason is Reason.DECLINED
    assert rs.stop(asking(), by=ClientType.ADMIN, now=T0).reason is Reason.CANCELLED


def test_duplicates_give_a_single_transition() -> None:
    state = asking()
    assert rs.request(state, request_id="r1", requested_by="emp", now=T0) == state
    armed = arming()
    assert rs.answer(armed, request_id="r1", consent=True, window_id="w2", now=T0) == armed
    stopped = rs.stop(on(), by=ClientType.ADMIN, now=T0)
    assert rs.stop(stopped, by=ClientType.ADMIN, now=T0) == stopped
    assert rs.stop(stopped, by=ClientType.CUSTOMER, now=T0) == stopped
    assert rs.request(stopped, request_id="r1", requested_by="emp", now=T0) == stopped


def test_conflicting_requests_and_answers_are_refused() -> None:
    with pytest.raises(rs.RecordingConflictError) as busy:
        rs.request(on(), request_id="r2", requested_by="emp", now=T0)
    assert busy.value.code == "RECORDING_BUSY"
    with pytest.raises(rs.RecordingConflictError):
        rs.answer(asking(), request_id="r2", consent=True, window_id="w", now=T0)
    with pytest.raises(rs.RecordingConflictError):
        rs.answer(arming(), request_id="r1", consent=False, window_id="w", now=T0)


def test_a_request_after_a_yes_is_a_resume() -> None:
    stopped = rs.stop(on(), by=ClientType.CUSTOMER, now=T0)
    again = rs.request(stopped, request_id="r2", requested_by="emp", now=T0)
    assert again.request_kind == "resume"


def test_a_stale_acknowledgement_changes_nothing() -> None:
    state = arming()
    assert rs.acknowledge(state, role=ClientType.ADMIN, version=state.state_version - 1) == state


def test_the_session_end_turns_everything_off() -> None:
    for state in (asking(), arming(), on()):
        ended = rs.end(state, now=T0)
        assert (ended.phase, ended.reason) == (Phase.OFF, Reason.SESSION_ENDED)
    assert rs.end(RecordingState(), now=T0) == RecordingState()


def test_pause_applies_only_while_arming_or_on() -> None:
    assert rs.pause(asking(), reason=Reason.POLICY, now=T0) == asking()
    paused = rs.pause(on(), reason=Reason.POLICY, now=T0)
    assert rs.pause(paused, reason=Reason.STORAGE, now=T0) == paused


def live_on() -> rs.Snapshot:
    return rs.snapshot(acked(on()), live=True)


def test_a_message_is_archivable_only_if_on_unchanged_acked_and_live_at_both_points() -> None:
    held = live_on()
    assert rs.archivable(held, held)
    assert not rs.archivable(held, replace(held, live=False))
    assert not rs.archivable(replace(held, acked_customer=held.state_version - 1), held)
    assert not rs.archivable(held, replace(held, phase=Phase.PAUSED))
    later = replace(held, state_version=held.state_version + 2)
    later = replace(later, acked_admin=later.state_version, acked_customer=later.state_version)
    assert later.holds()
    assert not rs.archivable(held, later)


def test_an_on_that_one_screen_never_acknowledged_pauses_after_ten_seconds() -> None:
    """A lost acknowledgement must not leave both screens showing a recording that is not stored."""
    half = rs.acknowledge(on(), role=ClientType.ADMIN, version=on().state_version)
    assert (
        rs.advance(half, now=T0 + rs.ACK_TIMEOUT - timedelta(seconds=1), live=True, ready=True)
        == half
    )
    paused = rs.advance(half, now=T0 + rs.ACK_TIMEOUT, live=True, ready=True)
    assert (paused.phase, paused.reason) == (Phase.PAUSED, Reason.UNACKNOWLEDGED)
    settled = rs.advance(acked(on()), now=T0 + timedelta(hours=1), live=True, ready=True)
    assert settled.phase is Phase.ON
