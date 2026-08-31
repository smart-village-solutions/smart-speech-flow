"""Regression coverage for issue #189.

The gateway pipeline entry points are synchronous and spend their time in
blocking ``requests.post`` calls. Calling them straight from an ``async def``
route handler pins the single event loop thread for the whole pipeline, which
serialises every session and starves health checks and WebSocket heartbeats.

These tests pin the non-blocking property itself, not an implementation detail:
the pipeline must not run on the event loop thread, two messages must make
progress at the same time, and the loop must keep ticking while a pipeline is
in flight.
"""

import asyncio
import importlib
import threading
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.api_gateway.session_manager import SessionManager, SessionStatus

# routes/__init__.py re-exports the endpoint functions under their module names,
# so `routes.upload` is the handler rather than the module. Import by path.
upload_route = importlib.import_module("services.api_gateway.routes.upload")
pipeline_route = importlib.import_module("services.api_gateway.routes.pipeline")

AUDIO_BYTES = b"RIFF" + b"fake_wav_audio_data" + b"\x00" * 100

PIPELINE_SUCCESS = {
    "error": False,
    "asr_text": "Guten Tag",
    "translation_text": "Good day",
    "audio_bytes": b"fake_output_audio",
}

TEXT_PIPELINE_SUCCESS = {
    "error": False,
    "translation_text": "Guten Tag",
    "audio_bytes": b"fake_output_audio",
    "debug": {},
}

# Long enough that a blocked loop is unmistakable, short enough to keep the
# suite fast. The assertions carry a wide margin so CI jitter cannot flip them.
BLOCK_SECONDS = 0.4
SAFETY_TIMEOUT = 15.0


@pytest.fixture
def session_manager():
    return SessionManager()


async def _make_active_session(manager: SessionManager) -> str:
    session_id = await manager.create_admin_session()
    session = manager.get_session(session_id)
    session.status = SessionStatus.ACTIVE
    session.customer_language = "en"
    return session_id


def _audio_request() -> Mock:
    request = Mock()
    request.headers = {"content-type": "multipart/form-data; boundary=boundary"}
    mock_file = Mock()
    mock_file.read = AsyncMock(return_value=AUDIO_BYTES)
    request.form = AsyncMock(
        return_value={
            "file": mock_file,
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin",
        }
    )
    return request


def _text_request() -> Mock:
    request = Mock()
    request.headers = {"content-type": "application/json"}
    request.json = AsyncMock(
        return_value={
            "text": "Guten Tag",
            "source_lang": "de",
            "target_lang": "en",
            "client_type": "admin",
        }
    )
    return request


class _ThreadRecorder:
    """Stands in for a pipeline function and records where it ran."""

    def __init__(self, result):
        self._result = result
        self.thread_ids: list[int] = []

    def __call__(self, *args, **kwargs):
        self.thread_ids.append(threading.get_ident())
        return dict(self._result)


class TestPipelineRunsOffTheEventLoop:
    """The pipeline body must execute on a worker thread, not the loop thread."""

    @pytest.mark.asyncio
    async def test_audio_pipeline_runs_off_event_loop(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await _make_active_session(session_manager)
        recorder = _ThreadRecorder(PIPELINE_SUCCESS)
        loop_thread_id = threading.get_ident()

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(session_routes, "process_wav", new=recorder),
        ):
            await session_routes.process_audio_input(session_id, _audio_request(), 0.0)

        assert recorder.thread_ids, "process_wav was never called"
        assert recorder.thread_ids[0] != loop_thread_id, (
            "process_wav ran on the event loop thread; its blocking HTTP calls "
            "hold the loop for the whole pipeline"
        )

    @pytest.mark.asyncio
    async def test_text_pipeline_runs_off_event_loop(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await _make_active_session(session_manager)
        recorder = _ThreadRecorder(TEXT_PIPELINE_SUCCESS)
        loop_thread_id = threading.get_ident()

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(session_routes, "process_text_pipeline", new=recorder),
        ):
            await session_routes.process_text_input(session_id, _text_request(), 0.0)

        assert recorder.thread_ids, "process_text_pipeline was never called"
        assert (
            recorder.thread_ids[0] != loop_thread_id
        ), "process_text_pipeline ran on the event loop thread"

    @pytest.mark.asyncio
    async def test_legacy_upload_route_runs_off_event_loop(self):
        recorder = _ThreadRecorder(PIPELINE_SUCCESS)
        loop_thread_id = threading.get_ident()

        upload_file = Mock()
        upload_file.read = AsyncMock(return_value=AUDIO_BYTES)

        with patch.object(upload_route, "process_wav", new=recorder):
            await upload_route.upload(
                request=Mock(), file=upload_file, source_lang="de", target_lang="en"
            )

        assert recorder.thread_ids, "process_wav was never called"
        assert (
            recorder.thread_ids[0] != loop_thread_id
        ), "the /upload route ran the pipeline on the event loop thread"

    @pytest.mark.asyncio
    async def test_legacy_pipeline_route_runs_off_event_loop(self):
        recorder = _ThreadRecorder(PIPELINE_SUCCESS)
        loop_thread_id = threading.get_ident()

        upload_file = Mock()
        upload_file.read = AsyncMock(return_value=AUDIO_BYTES)

        request = Mock()
        request.query_params = {}
        request.headers = {}

        with patch.object(pipeline_route, "process_wav", new=recorder):
            await pipeline_route.pipeline(
                request=request,
                file=upload_file,
                source_lang="de",
                target_lang="en",
                debug=None,
            )

        assert recorder.thread_ids, "process_wav was never called"
        assert (
            recorder.thread_ids[0] != loop_thread_id
        ), "the /pipeline route ran the pipeline on the event loop thread"


class TestConcurrentProgress:
    """Two independent messages must make progress concurrently."""

    @pytest.mark.asyncio
    async def test_two_audio_messages_progress_concurrently(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        first = await _make_active_session(session_manager)
        second = await _make_active_session(session_manager)

        # Trips only if both pipelines are inside the barrier at the same time.
        # Serialised execution breaks it instead, which fails the test.
        barrier = threading.Barrier(2)

        def rendezvous(*args, **kwargs):
            barrier.wait(timeout=BLOCK_SECONDS * 10)
            return dict(PIPELINE_SUCCESS)

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(session_routes, "process_wav", new=rendezvous),
        ):
            results = await asyncio.wait_for(
                asyncio.gather(
                    session_routes.process_audio_input(first, _audio_request(), 0.0),
                    session_routes.process_audio_input(second, _audio_request(), 0.0),
                ),
                timeout=SAFETY_TIMEOUT,
            )

        assert [result.status for result in results] == ["success", "success"]


class TestEventLoopResponsiveness:
    """Health checks and heartbeats must still be served mid-pipeline."""

    @staticmethod
    def _blocking_pipeline(entered: threading.Event, result):
        def run(*args, **kwargs):
            entered.set()
            time.sleep(BLOCK_SECONDS)
            return dict(result)

        return run

    async def _count_ticks_during(self, coro, entered: threading.Event) -> int:
        """Ticks the loop while ``coro`` runs, counting only in-flight ticks."""
        task = asyncio.create_task(coro)
        deadline = time.perf_counter() + SAFETY_TIMEOUT

        while not entered.is_set() and not task.done():
            if time.perf_counter() > deadline:
                task.cancel()
                pytest.fail("pipeline never started")
            await asyncio.sleep(0.005)

        ticks = 0
        while not task.done():
            if time.perf_counter() > deadline:
                task.cancel()
                pytest.fail("pipeline never finished")
            await asyncio.sleep(0.01)
            ticks += 1

        await task
        return ticks

    @pytest.mark.asyncio
    async def test_loop_keeps_ticking_during_audio_pipeline(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await _make_active_session(session_manager)
        entered = threading.Event()

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes,
                "process_wav",
                new=self._blocking_pipeline(entered, PIPELINE_SUCCESS),
            ),
        ):
            ticks = await self._count_ticks_during(
                session_routes.process_audio_input(session_id, _audio_request(), 0.0),
                entered,
            )

        # A free loop manages roughly BLOCK_SECONDS / 0.01 ticks; a blocked one
        # manages none. The threshold sits an order of magnitude below the
        # expected count so scheduling jitter cannot flip the result.
        assert ticks >= 5, (
            f"event loop completed only {ticks} ticks while the audio pipeline "
            "was in flight; it was blocked"
        )

    @pytest.mark.asyncio
    async def test_loop_keeps_ticking_during_text_pipeline(self, session_manager):
        from services.api_gateway.routes import session as session_routes

        session_id = await _make_active_session(session_manager)
        entered = threading.Event()

        with (
            patch.object(session_routes, "session_manager", session_manager),
            patch.object(
                session_routes,
                "process_text_pipeline",
                new=self._blocking_pipeline(entered, TEXT_PIPELINE_SUCCESS),
            ),
        ):
            ticks = await self._count_ticks_during(
                session_routes.process_text_input(session_id, _text_request(), 0.0),
                entered,
            )

        assert ticks >= 5, (
            f"event loop completed only {ticks} ticks while the text pipeline "
            "was in flight; it was blocked"
        )


def test_unused_process_wav_for_session_helper_is_gone():
    """#189 asks for the dead session helper to be removed."""
    from services.api_gateway import pipeline_logic

    assert not hasattr(pipeline_logic, "process_wav_for_session")
