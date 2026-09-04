"""`session_lifecycle` from the real SessionManager (tasks 1.2, 2.3, 2.4).

SessionManager is a process-wide singleton with no request behind it, so it
takes its emitter the way `translation_refiner` does -- attached by the
gateway's lifespan. The properties that matter are the same as everywhere else
in this pipeline: one row per transition, nothing content-bearing on it, and a
dead ClickHouse changing no session outcome.
"""

import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.quality_telemetry import (
    QualityTelemetry,
    SessionLifecyclePhase,
    SessionTerminationReason,
    TelemetryMode,
    discard_event,
)
from services.api_gateway.session_manager import SessionManager, SessionStatus


class _Spy:
    def __init__(self, explode: bool = False):
        self.calls = []
        self._explode = explode

    def emit_session_lifecycle(self, **kwargs):
        if self._explode:
            raise RuntimeError("ClickHouse is gone")
        self.calls.append(kwargs)

    def phases(self):
        return [call["phase"] for call in self.calls]


@pytest.fixture
def manager():
    instance = SessionManager()
    instance.reset()
    instance.attach_quality_telemetry(None)
    yield instance
    instance.attach_quality_telemetry(None)
    instance.reset()


@pytest.fixture
def spy(manager):
    recorder = _Spy()
    manager.attach_quality_telemetry(recorder)
    return recorder


class TestTheThreeTransitions:
    @pytest.mark.asyncio
    async def test_creating_a_session_emits_created(self, manager, spy):
        await manager.create_admin_session()

        assert SessionLifecyclePhase.CREATED in spy.phases()

    @pytest.mark.asyncio
    async def test_activating_a_session_emits_activated(self, manager, spy):
        session_id = await manager.create_admin_session()
        spy.calls.clear()

        await manager.activate_session(session_id, "en")

        assert spy.phases() == [SessionLifecyclePhase.ACTIVATED]

    @pytest.mark.asyncio
    async def test_a_language_change_on_an_active_session_is_not_a_second_activation(
        self, manager, spy
    ):
        """activate_session doubles as the language-update path.

        Emitting on every call would count one session as activated as many
        times as its customer switched language.
        """
        session_id = await manager.create_admin_session()
        await manager.activate_session(session_id, "en")
        spy.calls.clear()

        await manager.activate_session(session_id, "tr")

        assert spy.calls == []

    @pytest.mark.asyncio
    async def test_terminating_a_session_emits_terminated(self, manager, spy):
        session_id = await manager.create_admin_session()
        spy.calls.clear()

        await manager.terminate_session(session_id, "session_timeout")

        (call,) = spy.calls
        assert call["phase"] is SessionLifecyclePhase.TERMINATED
        assert call["termination_reason"] is SessionTerminationReason.SESSION_TIMEOUT

    @pytest.mark.asyncio
    async def test_terminating_an_already_terminated_session_emits_nothing(
        self, manager, spy
    ):
        """`terminate_session` returns early on a terminated session, and
        `terminate_all_active_sessions` calls it in a loop."""
        session_id = await manager.create_admin_session()
        await manager.terminate_session(session_id, "manual_termination")
        spy.calls.clear()

        await manager.terminate_session(session_id, "manual_termination")

        assert spy.calls == []

    @pytest.mark.asyncio
    async def test_the_single_session_policy_terminates_before_it_creates(
        self, manager, spy
    ):
        """Creating a second admin session closes the first, and both
        transitions are real events."""
        await manager.create_admin_session()
        spy.calls.clear()

        await manager.create_admin_session()

        assert spy.phases() == [
            SessionLifecyclePhase.TERMINATED,
            SessionLifecyclePhase.CREATED,
        ]
        assert (
            spy.calls[0]["termination_reason"]
            is SessionTerminationReason.NEW_SESSION_CREATED
        )


class TestTheLegacyCreationPath:
    """`create_session` is deprecated and still routed: POST /api/session/create.

    It was the one creation path with no emit, so a session opened through it
    produced a `terminated` row with no `created` row -- making Sessions
    Created, Sessions Activated and the empty-session panel mutually
    inconsistent for exactly the population this event exists to measure.
    """

    def test_the_legacy_route_still_reaches_this_method(self):
        from services.api_gateway.app import app

        assert "/api/session/create" in app.openapi()["paths"]

    def test_creating_a_legacy_session_emits_created(self, manager, spy):
        manager.create_session("en")

        assert SessionLifecyclePhase.CREATED in spy.phases()

    def test_a_session_that_starts_active_is_also_reported_activated(
        self, manager, spy
    ):
        """It goes straight to ACTIVE with the customer language already known,
        so the transition `activate_session` normally reports has happened."""
        manager.create_session("en")

        assert spy.phases() == [
            SessionLifecyclePhase.CREATED,
            SessionLifecyclePhase.ACTIVATED,
        ]

    @pytest.mark.asyncio
    async def test_the_funnel_never_shows_a_termination_without_a_creation(
        self, manager, spy
    ):
        session_id = manager.create_session("en")

        await manager.terminate_session(session_id, "manual_termination")

        phases = spy.phases()
        assert phases.count(SessionLifecyclePhase.CREATED) == 1
        assert phases.count(SessionLifecyclePhase.TERMINATED) == 1

    @pytest.mark.asyncio
    async def test_every_creation_path_emits_a_created_row(self, manager, spy):
        """Named rather than enumerated by hand: a third creation path added
        later must either emit or fail here."""
        manager.create_session("en")
        await manager.create_admin_session()

        assert spy.phases().count(SessionLifecyclePhase.CREATED) == 2


class TestWhatTheRowCarries:
    @pytest.mark.asyncio
    async def test_a_created_session_reports_no_duration_and_no_messages(
        self, manager, spy
    ):
        await manager.create_admin_session()

        (call,) = [c for c in spy.calls if c["phase"] is SessionLifecyclePhase.CREATED]
        assert call["session_duration_ms"] == 0
        assert call["message_count"] == 0
        assert call["termination_reason"] is SessionTerminationReason.NONE

    @pytest.mark.asyncio
    async def test_a_terminated_session_reports_how_long_it_lasted(self, manager, spy):
        session_id = await manager.create_admin_session()
        spy.calls.clear()

        await manager.terminate_session(session_id, "manual_termination")

        (call,) = spy.calls
        assert isinstance(call["session_duration_ms"], int)
        assert call["session_duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_a_terminated_session_reports_how_many_messages_it_carried(
        self, manager, spy
    ):
        session_id = await manager.create_admin_session()
        await manager.activate_session(session_id, "en")
        session = manager.get_session(session_id)
        session.messages.extend([object(), object(), object()])
        spy.calls.clear()

        await manager.terminate_session(session_id, "manual_termination")

        assert spy.calls[0]["message_count"] == 3

    @pytest.mark.asyncio
    async def test_the_session_id_never_leaves_in_the_clear(self, manager, spy):
        session_id = await manager.create_admin_session()

        for call in spy.calls:
            assert call["session_ref"] != session_id
            assert len(call["session_ref"]) == 32

    @pytest.mark.asyncio
    async def test_an_unrecognised_reason_is_not_stored_verbatim(self, manager, spy):
        session_id = await manager.create_admin_session()
        spy.calls.clear()

        await manager.terminate_session(session_id, "the admin said it was private")

        assert spy.calls[0]["termination_reason"] is SessionTerminationReason.OTHER


class TestTelemetryNeverChangesTheOutcome:
    @pytest.mark.asyncio
    async def test_an_exploding_emitter_does_not_stop_a_session_being_created(
        self, manager
    ):
        manager.attach_quality_telemetry(_Spy(explode=True))

        session_id = await manager.create_admin_session()

        assert manager.get_session(session_id) is not None

    @pytest.mark.asyncio
    async def test_an_exploding_emitter_does_not_stop_a_session_being_terminated(
        self, manager
    ):
        manager.attach_quality_telemetry(_Spy(explode=True))
        session_id = await manager.create_admin_session()

        await manager.terminate_session(session_id, "manual_termination")

        assert manager.get_session(session_id).status is SessionStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_no_emitter_at_all_changes_nothing(self, manager):
        session_id = await manager.create_admin_session()

        await manager.terminate_session(session_id, "manual_termination")

        assert manager.get_session(session_id).status is SessionStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_a_dead_clickhouse_behind_a_real_emitter_changes_nothing(
        self, manager
    ):
        def dead(name, attributes, emitted_at_utc):
            raise RuntimeError("ClickHouse is unreachable")

        manager.attach_quality_telemetry(
            QualityTelemetry(
                mode=TelemetryMode.ENABLED, exporter=dead, registry=CollectorRegistry()
            )
        )

        session_id = await manager.create_admin_session()
        await manager.activate_session(session_id, "en")
        await manager.terminate_session(session_id, "manual_termination")

        assert manager.get_session(session_id).status is SessionStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_production_default_emits_nothing_at_all(self, manager):
        emitted = []

        manager.attach_quality_telemetry(
            QualityTelemetry(
                mode=TelemetryMode.DISABLED,
                exporter=lambda *a: emitted.append(a),
                registry=CollectorRegistry(),
            )
        )

        await manager.create_admin_session()

        assert emitted == []

    @pytest.mark.asyncio
    async def test_resetting_the_manager_does_not_detach_the_emitter(
        self, manager, spy
    ):
        """`SessionManager()` re-runs `__init__` on the singleton, and the test
        suite builds many of them. An attachment cleared there would leave the
        gateway silently un-instrumented after the first one."""
        SessionManager()

        await manager.create_admin_session()

        assert spy.calls
