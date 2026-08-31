import asyncio
import threading
import time
from unittest.mock import Mock, patch

import httpx
import pytest
from prometheus_client import CollectorRegistry

from services.api_gateway.pipeline_admission import (
    PipelineAdmission,
    PipelineAdmissionConfig,
    PipelineAdmissionMetrics,
    PipelineBusyError,
    run_pipeline,
)
from services.api_gateway.session_manager import SessionManager
from tests.pipeline_helpers import (
    PIPELINE_SUCCESS,
    SAFETY_TIMEOUT,
    TEXT_PIPELINE_SUCCESS,
    audio_request,
    health_route,
    legacy_pipeline_request,
    make_active_session,
    pipeline_route,
    request_with,
    text_request,
    upload_file,
    upload_route,
)

# Short enough to keep the suite fast; every assertion below is about ordering
# or rejection, never about a wall-clock duration.
SHORT_WAIT = 0.05


def _metrics() -> PipelineAdmissionMetrics:
    """Metrics on a throwaway registry, so each test registers its own series."""
    return PipelineAdmissionMetrics(CollectorRegistry())


def _admission(max_concurrent: int, wait: float = SHORT_WAIT, *, metrics=None) -> PipelineAdmission:
    return PipelineAdmission(
        PipelineAdmissionConfig(max_concurrent=max_concurrent, queue_wait_seconds=wait),
        metrics=metrics,
    )


def _noop() -> None:
    return None


async def _wait_for_in_flight(admission: PipelineAdmission, count: int) -> None:
    """Slots are released from worker threads, so settling takes a loop tick."""
    deadline = time.perf_counter() + SAFETY_TIMEOUT
    while admission.in_flight != count:
        if time.perf_counter() > deadline:
            raise AssertionError(f"in_flight settled at {admission.in_flight}, expected {count}")
        await asyncio.sleep(0.005)


class _Saturated:
    """Holds every slot with real thread work, so the next request is rejected."""

    def __init__(self, admission: PipelineAdmission) -> None:
        self._admission = admission
        self._finish = threading.Event()
        self._holders: list[asyncio.Task] = []

    def _block(self):
        self._finish.wait(SAFETY_TIMEOUT)
        return dict(PIPELINE_SUCCESS)

    async def __aenter__(self) -> "_Saturated":
        wanted = self._admission.config.max_concurrent
        self._holders = [
            asyncio.create_task(self._admission.run(self._block)) for _ in range(wanted)
        ]
        await _wait_for_in_flight(self._admission, wanted)
        return self

    async def __aexit__(self, *_exc_info) -> bool:
        self._finish.set()
        await asyncio.wait_for(asyncio.gather(*self._holders), timeout=SAFETY_TIMEOUT)
        return False


@pytest.fixture
def session_manager():
    return SessionManager()


class TestConfiguration:
    """The limit and wait timeout are typed, documented configuration."""

    def test_defaults_are_conservative(self, monkeypatch):
        monkeypatch.delenv("MAX_CONCURRENT_PIPELINES", raising=False)
        monkeypatch.delenv("PIPELINE_QUEUE_WAIT_SECONDS", raising=False)

        config = PipelineAdmissionConfig()

        assert config.max_concurrent == 2
        assert config.queue_wait_seconds == pytest.approx(10.0)

    def test_reads_environment_at_instantiation(self, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_PIPELINES", "7")
        monkeypatch.setenv("PIPELINE_QUEUE_WAIT_SECONDS", "2.5")

        config = PipelineAdmissionConfig()

        assert config.max_concurrent == 7
        assert config.queue_wait_seconds == pytest.approx(2.5)

    def test_unparseable_environment_falls_back_to_default(self, monkeypatch):
        """A typo in an env var must not stop the gateway from booting."""
        monkeypatch.setenv("MAX_CONCURRENT_PIPELINES", "not-a-number")
        monkeypatch.setenv("PIPELINE_QUEUE_WAIT_SECONDS", "")

        config = PipelineAdmissionConfig()

        assert config.max_concurrent == 2
        assert config.queue_wait_seconds == pytest.approx(10.0)

    def test_negative_limit_falls_back_rather_than_disabling(self, monkeypatch):
        """Only an explicit 0 disables; a negative is a typo, not consent."""
        monkeypatch.setenv("MAX_CONCURRENT_PIPELINES", "-1")

        config = PipelineAdmissionConfig()

        assert config.max_concurrent == 2
        assert PipelineAdmission(config).enabled is True

    def test_negative_wait_falls_back_to_default(self):
        config = PipelineAdmissionConfig(max_concurrent=1, queue_wait_seconds=-5.0)

        assert config.queue_wait_seconds == pytest.approx(10.0)

    def test_unparseable_wait_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("PIPELINE_QUEUE_WAIT_SECONDS", "ten-seconds")

        assert PipelineAdmissionConfig().queue_wait_seconds == pytest.approx(10.0)

    def test_zero_is_the_documented_kill_switch(self, monkeypatch):
        monkeypatch.setenv("MAX_CONCURRENT_PIPELINES", "0")

        config = PipelineAdmissionConfig()

        assert config.max_concurrent == 0
        assert PipelineAdmission(config).enabled is False


class TestSlotBounding:
    """The component admits up to the limit and rejects beyond it."""

    @pytest.mark.asyncio
    async def test_admits_up_to_the_limit_concurrently(self):
        admission = _admission(2, wait=SAFETY_TIMEOUT)
        # Trips only if both pipelines are inside their slots at the same time.
        barrier = threading.Barrier(2)

        def rendezvous():
            barrier.wait(timeout=SAFETY_TIMEOUT)
            return dict(PIPELINE_SUCCESS)

        await asyncio.wait_for(
            asyncio.gather(admission.run(rendezvous), admission.run(rendezvous)),
            timeout=SAFETY_TIMEOUT,
        )

    @pytest.mark.asyncio
    async def test_rejects_beyond_the_limit(self):
        admission = _admission(1)

        async with _Saturated(admission):
            with pytest.raises(PipelineBusyError) as excinfo:
                await admission.run(_noop)

        assert excinfo.value.max_concurrent == 1
        assert excinfo.value.retry_after_seconds >= 1
        assert excinfo.value.retry_after_header == "1"

    @pytest.mark.asyncio
    async def test_slot_is_returned_after_use(self):
        admission = _admission(1)

        await admission.run(_noop)
        # Would raise PipelineBusyError if the first slot had leaked.
        await admission.run(_noop)
        assert admission.in_flight == 0

    @pytest.mark.asyncio
    async def test_slot_is_returned_when_the_pipeline_raises(self):
        admission = _admission(1)

        def boom():
            raise ValueError("pipeline blew up")

        with pytest.raises(ValueError):
            await admission.run(boom)

        await admission.run(_noop)

    @pytest.mark.asyncio
    async def test_a_waiter_is_admitted_once_a_slot_frees(self):
        admission = _admission(1, wait=SAFETY_TIMEOUT)
        order: list[str] = []
        finish = threading.Event()

        def first():
            order.append("first-in")
            finish.wait(SAFETY_TIMEOUT)
            order.append("first-out")

        def second():
            order.append("second-in")

        first_task = asyncio.create_task(admission.run(first))
        await _wait_for_in_flight(admission, 1)
        second_task = asyncio.create_task(admission.run(second))

        finish.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=SAFETY_TIMEOUT)

        assert order == ["first-in", "first-out", "second-in"]

    @pytest.mark.asyncio
    async def test_zero_limit_disables_the_bound(self):
        admission = _admission(0)
        barrier = threading.Barrier(3)

        def rendezvous():
            barrier.wait(timeout=SAFETY_TIMEOUT)

        await asyncio.wait_for(
            asyncio.gather(*(admission.run(rendezvous) for _ in range(3))),
            timeout=SAFETY_TIMEOUT,
        )


class TestCancellationCannotFreeCapacityEarly:
    """A cancelled request must not hand back a slot its thread is still using."""

    @pytest.mark.asyncio
    async def test_cancelled_request_keeps_its_slot_until_the_thread_finishes(self):
        admission = _admission(1)
        running = threading.Event()
        finish = threading.Event()

        def blocking():
            running.set()
            finish.wait(SAFETY_TIMEOUT)
            return dict(PIPELINE_SUCCESS)

        task = asyncio.create_task(admission.run(blocking))
        await asyncio.wait_for(
            asyncio.to_thread(running.wait, SAFETY_TIMEOUT), timeout=SAFETY_TIMEOUT
        )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # asyncio.to_thread cannot interrupt the call it started, so the
        # pipeline is still on the GPU and its slot must stay taken.
        assert admission.in_flight == 1
        with pytest.raises(PipelineBusyError):
            await admission.run(_noop)

        finish.set()
        await _wait_for_in_flight(admission, 0)
        # Capacity comes back once the thread really is done.
        await admission.run(_noop)

    def test_release_never_raises_when_the_loop_is_already_gone(self):
        """Reaches for the private because this runs in a worker thread's finally.

        At shutdown the loop can be closed before the pipeline returns. Raising
        there would surface as a spurious pipeline error, and there is no
        capacity left to account for anyway.
        """
        admission = _admission(1)
        closed_loop = Mock()
        closed_loop.call_soon_threadsafe.side_effect = RuntimeError("Event loop is closed")

        admission._schedule_release(closed_loop)

        closed_loop.call_soon_threadsafe.assert_called_once()


class TestMetrics:
    """Metrics support capacity tuning through load tests."""

    @staticmethod
    def _sample(metric, suffix=""):
        name = metric._name + suffix
        for collected in metric.collect():
            for sample in collected.samples:
                if sample.name == name:
                    return sample.value
        raise AssertionError(f"no sample named {name}")

    @pytest.mark.asyncio
    async def test_in_flight_rises_and_falls(self):
        metrics = _metrics()
        admission = _admission(1, metrics=metrics)
        inside = None
        release = threading.Event()

        def observe():
            release.wait(SAFETY_TIMEOUT)

        task = asyncio.create_task(admission.run(observe))
        await _wait_for_in_flight(admission, 1)
        inside = self._sample(metrics.in_flight)
        release.set()
        await asyncio.wait_for(task, timeout=SAFETY_TIMEOUT)

        assert inside == 1
        assert self._sample(metrics.in_flight) == 0

    @pytest.mark.asyncio
    async def test_queue_wait_is_observed_when_admitted(self):
        metrics = _metrics()
        admission = _admission(1, metrics=metrics)

        await admission.run(_noop)

        assert self._sample(metrics.queue_wait, "_count") == 1

    @pytest.mark.asyncio
    async def test_queue_wait_is_observed_on_rejection(self):
        """A histogram blind to rejections reports 'seated instantly' at saturation."""
        metrics = _metrics()
        admission = _admission(1, metrics=metrics)

        async with _Saturated(admission):
            with pytest.raises(PipelineBusyError):
                await admission.run(_noop)

        # One holder was admitted, one request was rejected: both waited.
        assert self._sample(metrics.queue_wait, "_count") == 2
        assert self._sample(metrics.rejected, "_total") == 1
        # The rejected request waited the full window, so the sum must reflect
        # it rather than rounding to nothing.
        assert self._sample(metrics.queue_wait, "_sum") >= SHORT_WAIT

    @pytest.mark.asyncio
    async def test_rejection_is_counted(self):
        metrics = _metrics()
        admission = _admission(1, metrics=metrics)

        async with _Saturated(admission):
            with pytest.raises(PipelineBusyError):
                await admission.run(_noop)

        assert self._sample(metrics.rejected, "_total") == 1


class TestRunPipelineHelper:
    """The handlers must degrade to unbounded rather than fail on a mock request."""

    @pytest.mark.asyncio
    async def test_runs_unbounded_when_state_has_no_admission(self):
        assert await run_pipeline(Mock(), lambda: "ran") == "ran"

    @pytest.mark.asyncio
    async def test_runs_unbounded_when_request_has_no_app(self):
        assert await run_pipeline(object(), lambda: "ran") == "ran"

    @pytest.mark.asyncio
    async def test_passes_arguments_through(self):
        result = await run_pipeline(Mock(), lambda a, b, c=None: (a, b, c), 1, 2, c=3)

        assert result == (1, 2, 3)

    @pytest.mark.asyncio
    async def test_enforces_when_a_real_component_is_present(self):
        admission = _admission(1)
        request = request_with(admission)

        async with _Saturated(admission):
            with pytest.raises(PipelineBusyError):
                await run_pipeline(request, _noop)


class TestSystemBusyResponse:
    """A saturated system returns the standard envelope with SYSTEM_BUSY."""

    @pytest.mark.asyncio
    async def test_audio_path_returns_503_system_busy(self, session_manager):
        from fastapi import HTTPException

        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(session_routes, "process_wav", return_value=dict(PIPELINE_SUCCESS)),
        ):
            async with _Saturated(admission):
                with pytest.raises(HTTPException) as excinfo:
                    await session_routes.process_audio_input(
                        session_id, audio_request(admission), 0.0
                    )

        error = excinfo.value
        assert error.status_code == 503
        assert error.detail["error_code"] == "SYSTEM_BUSY"
        assert error.headers["Retry-After"] == "1"

    @pytest.mark.asyncio
    async def test_text_path_returns_503_system_busy(self, session_manager):
        from fastapi import HTTPException

        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=dict(TEXT_PIPELINE_SUCCESS)
            ),
        ):
            async with _Saturated(admission):
                with pytest.raises(HTTPException) as excinfo:
                    await session_routes.process_text_input(
                        session_id, text_request(admission), 0.0
                    )

        error = excinfo.value
        assert error.status_code == 503
        assert error.detail["error_code"] == "SYSTEM_BUSY"
        assert error.headers["Retry-After"] == "1"

    @pytest.mark.asyncio
    async def test_body_advises_the_same_delay_as_the_header(self, session_manager):
        """A client reading the body must not retry sooner than the header allows."""
        from fastapi import HTTPException

        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1, wait=0.2)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=dict(TEXT_PIPELINE_SUCCESS)
            ),
        ):
            async with _Saturated(admission):
                with pytest.raises(HTTPException) as excinfo:
                    await session_routes.process_text_input(
                        session_id, text_request(admission), 0.0
                    )

        error = excinfo.value
        assert error.detail["details"]["retry_after_seconds"] == int(error.headers["Retry-After"])
        # The raw window stays available, under a name that cannot be mistaken
        # for an advised delay.
        assert error.detail["details"]["queue_wait_seconds"] == pytest.approx(0.2)

    @pytest.mark.asyncio
    async def test_busy_error_does_not_become_a_500(self, session_manager):
        """send_unified_message catches broad Exceptions; SYSTEM_BUSY must survive."""
        from fastapi import HTTPException

        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=dict(TEXT_PIPELINE_SUCCESS)
            ),
        ):
            async with _Saturated(admission):
                with pytest.raises(HTTPException) as excinfo:
                    await session_routes.send_unified_message(session_id, text_request(admission))

        assert excinfo.value.status_code == 503
        assert excinfo.value.detail["error_code"] == "SYSTEM_BUSY"

    @pytest.mark.asyncio
    async def test_slot_is_released_so_the_next_message_succeeds(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes, "process_text_pipeline", return_value=dict(TEXT_PIPELINE_SUCCESS)
            ),
        ):
            first = await session_routes.process_text_input(
                session_id, text_request(admission), 0.0
            )
            second = await session_routes.process_text_input(
                session_id, text_request(admission), 0.0
            )

        assert first.status == "success"
        assert second.status == "success"
        assert admission.in_flight == 0


class TestEndToEndOverTheWire:
    """Proves env -> lifespan -> app.state -> route -> HTTP response, headers included."""

    @pytest.mark.asyncio
    async def test_saturated_gateway_answers_503_with_retry_after(self, monkeypatch):
        from services.api_gateway.app import app, lifespan
        from services.api_gateway.routes import session as session_routes
        from services.api_gateway.session_manager import session_manager as live_manager

        monkeypatch.setenv("MAX_CONCURRENT_PIPELINES", "1")
        monkeypatch.setenv("PIPELINE_QUEUE_WAIT_SECONDS", "0.1")

        started = threading.Event()
        finish = threading.Event()

        def blocking_text(*_args, **_kwargs):
            started.set()
            finish.wait(SAFETY_TIMEOUT)
            return dict(TEXT_PIPELINE_SUCCESS)

        payload = {
            "text": "Guten Tag",
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin",
        }

        async with lifespan(app):
            assert app.state.pipeline_admission.config.max_concurrent == 1

            session_id = await make_active_session(live_manager)
            url = f"/api/session/{session_id}/message"

            with patch.object(session_routes, "process_text_pipeline", new=blocking_text):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://gateway.test"
                ) as client:
                    holder = asyncio.create_task(client.post(url, json=payload))
                    await asyncio.wait_for(
                        asyncio.to_thread(started.wait, SAFETY_TIMEOUT),
                        timeout=SAFETY_TIMEOUT,
                    )

                    rejected = await asyncio.wait_for(
                        client.post(url, json=payload), timeout=SAFETY_TIMEOUT
                    )

                    finish.set()
                    admitted = await asyncio.wait_for(holder, timeout=SAFETY_TIMEOUT)

        assert rejected.status_code == 503
        assert rejected.headers["retry-after"] == "1"
        body = rejected.json()
        assert body["detail"]["error_code"] == "SYSTEM_BUSY"
        assert body["detail"]["details"]["retry_after_seconds"] == 1
        assert admitted.status_code == 200


class TestLegacyRoutesAreGated:
    """All four GPU call sites are bounded, not just the unified endpoint."""

    @pytest.mark.asyncio
    async def test_upload_route_reports_busy(self):
        admission = _admission(1)

        with patch.object(upload_route, "process_wav", return_value=dict(PIPELINE_SUCCESS)):
            async with _Saturated(admission):
                response = await upload_route.upload(
                    request=request_with(admission),
                    file=upload_file(),
                    source_lang="de",
                    target_lang="en",
                )

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"

    @pytest.mark.asyncio
    async def test_pipeline_route_reports_busy(self):
        admission = _admission(1)

        with patch.object(pipeline_route, "process_wav", return_value=dict(PIPELINE_SUCCESS)):
            async with _Saturated(admission):
                response = await pipeline_route.pipeline(
                    request=legacy_pipeline_request(admission),
                    file=upload_file(),
                    source_lang="de",
                    target_lang="en",
                    debug=None,
                )

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
        assert b"SYSTEM_BUSY" in response.body


class TestNonPipelineTrafficIsUnaffected:
    """Health and session-management traffic bypass the bound."""

    @pytest.mark.asyncio
    async def test_session_management_responds_while_saturated(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await make_active_session(session_manager)
        admission = _admission(1)

        async with _Saturated(admission):
            with patch.object(session_routes, "session_manager", session_manager):
                info = await asyncio.wait_for(
                    session_routes.get_session_info(session_id), timeout=1.0
                )
                active = await asyncio.wait_for(session_routes.get_active_sessions(), timeout=1.0)

        assert info["id"] == session_id
        assert "sessions" in active

    @pytest.mark.asyncio
    async def test_health_route_never_touches_the_bound(self):
        """/health is a sync def served off the loop and holds no slot."""
        admission = _admission(1)

        async with _Saturated(admission):
            with patch.object(health_route, "requests") as mock_requests:
                mock_requests.get.return_value = Mock(status_code=200)
                result = await asyncio.wait_for(asyncio.to_thread(health_route.health), timeout=1.0)

        assert set(result["services"].values()) == {"ok"}


class TestLifespanOwnership:
    """The component is created by the app lifespan, per #191."""

    def test_lifespan_publishes_admission_on_app_state(self):
        from fastapi.testclient import TestClient

        from services.api_gateway.app import app

        with TestClient(app):
            admission = app.state.pipeline_admission
            assert isinstance(admission, PipelineAdmission)
            # Not >= 1: 0 is the documented kill switch, and this test must not
            # fail for an operator who has set it.
            assert admission.config.max_concurrent >= 0

    def test_admission_is_not_a_module_level_singleton(self):
        """The semaphore must belong to the running app, not import time."""
        import services.api_gateway.pipeline_admission as module

        assert not hasattr(module, "pipeline_admission")


@pytest.mark.asyncio
async def test_bound_is_process_local_by_design():
    """Documents the #227 boundary: this bounds one replica, not the fleet."""
    first = _admission(1)
    second = _admission(1)

    async with _Saturated(first):
        # A second gateway process is unaffected by the first one's saturation.
        await second.run(_noop)
        assert first.in_flight == 1
