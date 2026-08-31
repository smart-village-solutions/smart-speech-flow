"""#190: translation inference must leave the event loop free, under a bound.

The module is loaded with ``torch``, ``transformers`` and ``prometheus_client``
stubbed, so CI needs no GPU wheels and no global metric registry. ``fastapi``
stays real: it is the only way to prove the ``Retry-After`` header on a
saturation 503 actually reaches a client rather than just existing in a dict.

Lives in ``tests/`` deliberately. CI runs ``pytest tests/`` and ``pytest.ini``
pins ``testpaths = tests``, so a guard placed in ``services/translation/tests/``
would never run.
"""

import asyncio
import importlib.util
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_service_app_helpers import (
    build_prometheus_stub,
    build_torch_stub,
    build_transformers_stub,
)

ROOT = Path(__file__).resolve().parents[1]

# Long enough that a blocked loop is unmistakable, short enough to keep the
# suite quick. Every assertion carries a wide margin so CI jitter cannot flip it.
BLOCK_SECONDS = 0.4
SAFETY_TIMEOUT = 15.0

PAYLOAD = {"text": "Hallo Welt", "source_lang": "de", "target_lang": "en"}


def load_translation(monkeypatch, **env):
    """Loads services/translation/app.py fresh, with GPU deps stubbed.

    ``env`` is applied before import because the module reads its admission
    settings into constants at import time, exactly as the rest of its config.
    """
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))

    for name, stub in (
        ("torch", build_torch_stub()),
        ("transformers", build_transformers_stub()),
        ("prometheus_client", build_prometheus_stub()),
    ):
        monkeypatch.setitem(sys.modules, name, stub)

    unique = f"translation_app_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(unique, ROOT / "services/translation/app.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique] = module
    monkeypatch.setitem(sys.modules, unique, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def translation(monkeypatch):
    return load_translation(monkeypatch)


def request_with(admission=None, payload=None, query_params=None):
    """A fake request whose app state carries ``admission`` (``None`` = unbounded)."""
    app = SimpleNamespace(state=SimpleNamespace(translation_admission=admission))

    class FakeRequest:
        def __init__(self):
            self.app = app
            self.query_params = query_params or {}

        async def json(self):
            return PAYLOAD if payload is None else payload

    return FakeRequest()


class _ThreadRecorder:
    """Stands in for _translate_texts and records where it ran."""

    def __init__(self, result=None, delay=0.0):
        self._result = result or ["translated"]
        self._delay = delay
        self.thread_ids: list[int] = []
        self.entered = threading.Event()

    def __call__(self, texts, *_args, **_kwargs):
        self.thread_ids.append(threading.get_ident())
        self.entered.set()
        if self._delay:
            time.sleep(self._delay)
        return list(self._result)


class _MetricsRecorder:
    """Captures what the admission component reports, since the stub metrics drop it."""

    def __init__(self):
        self.waits: list[float] = []
        self.rejections = 0
        self.in_flight_delta = 0

        recorder = self

        class _Gauge:
            def inc(self, *_a, **_k):
                recorder.in_flight_delta += 1

            def dec(self, *_a, **_k):
                recorder.in_flight_delta -= 1

        class _Histogram:
            def observe(self, value, *_a, **_k):
                recorder.waits.append(value)

        class _Counter:
            def inc(self, *_a, **_k):
                recorder.rejections += 1

        self.in_flight = _Gauge()
        self.queue_wait = _Histogram()
        self.rejected = _Counter()


class TestOffloadedFromTheEventLoop:
    """The blocking generate() call must not run on the loop thread."""

    @pytest.mark.asyncio
    async def test_translation_runs_off_the_event_loop(self, translation):
        recorder = _ThreadRecorder()
        translation._translate_texts = recorder
        loop_thread_id = threading.get_ident()

        await translation.translate(request_with())

        assert recorder.thread_ids, "_translate_texts was never called"
        assert recorder.thread_ids[0] != loop_thread_id, (
            "_translate_texts ran on the event loop thread; m2m_model.generate() "
            "holds the loop for the whole beam search"
        )

    @pytest.mark.asyncio
    async def test_loop_keeps_ticking_during_translation(self, translation):
        recorder = _ThreadRecorder(delay=BLOCK_SECONDS)
        translation._translate_texts = recorder

        task = asyncio.create_task(translation.translate(request_with()))
        deadline = time.perf_counter() + SAFETY_TIMEOUT

        while not recorder.entered.is_set() and not task.done():
            if time.perf_counter() > deadline:
                task.cancel()
                pytest.fail("translation never started")
            await asyncio.sleep(0.005)

        ticks = 0
        while not task.done():
            if time.perf_counter() > deadline:
                task.cancel()
                pytest.fail("translation never finished")
            await asyncio.sleep(0.01)
            ticks += 1

        await task

        # A free loop manages roughly BLOCK_SECONDS / 0.01 ticks; a blocked one
        # manages none. The threshold sits well below the expected count.
        assert ticks >= 5, (
            f"event loop completed only {ticks} ticks while translation was in "
            "flight; it was blocked"
        )

    @pytest.mark.asyncio
    async def test_health_stays_responsive_during_translation(self, translation):
        """The acceptance criterion, asserted against the handler itself."""
        recorder = _ThreadRecorder(delay=BLOCK_SECONDS)
        translation._translate_texts = recorder

        task = asyncio.create_task(translation.translate(request_with()))
        await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(None, recorder.entered.wait),
            timeout=SAFETY_TIMEOUT,
        )

        probe = await asyncio.wait_for(asyncio.to_thread(translation.health), timeout=2.0)
        assert probe["status"] == "ok"
        assert not task.done(), "translation finished before the probe; test proved nothing"

        await asyncio.wait_for(task, timeout=SAFETY_TIMEOUT)


class TestConcurrencyBound:
    """Concurrent translations progress, but never more than the limit at once."""

    @pytest.mark.asyncio
    async def test_two_translations_progress_concurrently(self, translation):
        admission = translation.TranslationAdmission(max_concurrent=2, queue_wait_seconds=5.0)
        # Trips only if both translations are inside the barrier at the same time.
        barrier = threading.Barrier(2)

        def rendezvous(texts, *_args, **_kwargs):
            barrier.wait(timeout=SAFETY_TIMEOUT)
            return ["translated"]

        translation._translate_texts = rendezvous

        responses = await asyncio.wait_for(
            asyncio.gather(
                translation.translate(request_with(admission)),
                translation.translate(request_with(admission)),
            ),
            timeout=SAFETY_TIMEOUT,
        )

        assert [response.status_code for response in responses] == [200, 200]

    @pytest.mark.asyncio
    async def test_bound_of_one_never_admits_two_at_once(self, translation):
        admission = translation.TranslationAdmission(max_concurrent=1, queue_wait_seconds=5.0)
        lock = threading.Lock()
        state = {"current": 0, "peak": 0}

        def observe(texts, *_args, **_kwargs):
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.05)
            with lock:
                state["current"] -= 1
            return ["translated"]

        translation._translate_texts = observe

        await asyncio.wait_for(
            asyncio.gather(*(translation.translate(request_with(admission)) for _ in range(4))),
            timeout=SAFETY_TIMEOUT,
        )

        assert state["peak"] == 1, f"{state['peak']} translations ran at once under a limit of 1"

    @pytest.mark.asyncio
    async def test_zero_disables_the_bound(self, translation):
        admission = translation.TranslationAdmission(max_concurrent=0)
        assert admission.enabled is False

        translation._translate_texts = _ThreadRecorder()
        response = await translation.translate(request_with(admission))
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_negative_limit_falls_back_to_the_default(self, translation):
        """A negative value is a typo, and silently unbounding the GPU is the
        dangerous reading of it. Only an explicit 0 disables."""
        admission = translation.TranslationAdmission(max_concurrent=-1)

        assert admission.enabled is True
        assert admission.max_concurrent == translation.DEFAULT_MAX_CONCURRENT_TRANSLATIONS

    @pytest.mark.asyncio
    async def test_non_positive_queue_wait_falls_back_to_the_default(self, translation):
        admission = translation.TranslationAdmission(queue_wait_seconds=0)

        assert admission.queue_wait_seconds == translation.DEFAULT_TRANSLATION_QUEUE_WAIT_SECONDS


class TestSaturationResponse:
    """A saturated queue must produce an attributable 503, not a timeout."""

    @staticmethod
    def _saturate(translation, admission):
        """Occupies every slot until the returned event is set."""
        release = threading.Event()
        occupied = threading.Barrier(admission.max_concurrent + 1)

        def hold(texts, *_args, **_kwargs):
            occupied.wait(timeout=SAFETY_TIMEOUT)
            release.wait(timeout=SAFETY_TIMEOUT)
            return ["translated"]

        translation._translate_texts = hold
        holders = [
            asyncio.create_task(translation.translate(request_with(admission)))
            for _ in range(admission.max_concurrent)
        ]
        return release, occupied, holders

    @pytest.mark.asyncio
    async def test_saturated_request_returns_503_with_retry_after(self, translation):
        admission = translation.TranslationAdmission(max_concurrent=1, queue_wait_seconds=0.05)
        release, occupied, holders = self._saturate(translation, admission)

        await asyncio.to_thread(occupied.wait, SAFETY_TIMEOUT)

        with pytest.raises(translation.HTTPException) as caught:
            await translation.translate(request_with(admission))

        assert caught.value.status_code == 503
        assert caught.value.headers["Retry-After"] == "1"

        release.set()
        await asyncio.wait_for(asyncio.gather(*holders), timeout=SAFETY_TIMEOUT)

    @pytest.mark.asyncio
    async def test_busy_does_not_become_a_500(self, translation):
        """translate() ends in a broad `except Exception` that would happily
        turn a RuntimeError subclass into 'Translation failed: ...'."""
        admission = translation.TranslationAdmission(max_concurrent=1, queue_wait_seconds=0.05)
        release, occupied, holders = self._saturate(translation, admission)

        await asyncio.to_thread(occupied.wait, SAFETY_TIMEOUT)

        with pytest.raises(translation.HTTPException) as caught:
            await translation.translate(request_with(admission))

        assert caught.value.status_code != 500
        assert "Translation failed" not in str(caught.value.detail)

        release.set()
        await asyncio.wait_for(asyncio.gather(*holders), timeout=SAFETY_TIMEOUT)

    @pytest.mark.asyncio
    async def test_busy_returns_the_debug_envelope_when_debug_is_requested(self, translation):
        """The gateway passes `debug` through on every pipeline call, so the
        saturation path has to honour it like every other failure here."""
        admission = translation.TranslationAdmission(max_concurrent=1, queue_wait_seconds=0.05)
        release, occupied, holders = self._saturate(translation, admission)

        await asyncio.to_thread(occupied.wait, SAFETY_TIMEOUT)

        response = await translation.translate(
            request_with(admission, payload={**PAYLOAD, "debug": "true"})
        )

        assert response.status_code == 503
        assert response.headers["retry-after"] == "1"
        assert b'"translations":null' in response.body
        assert b"Translation service busy" in response.body

        release.set()
        await asyncio.wait_for(asyncio.gather(*holders), timeout=SAFETY_TIMEOUT)

    @pytest.mark.asyncio
    async def test_busy_reports_retry_after_consistently_in_body_and_header(self, translation):
        admission = translation.TranslationAdmission(max_concurrent=1, queue_wait_seconds=2.4)
        busy = translation.TranslationBusyError(
            max_concurrent=admission.max_concurrent,
            queue_wait_seconds=admission.queue_wait_seconds,
            waited_seconds=2.4,
        )

        # Whole seconds, never below one, so a client reading the header and a
        # client reading the message wait the same amount of time.
        assert busy.retry_after_seconds == 3
        assert busy.retry_after_header == "3"

    @pytest.mark.asyncio
    async def test_rejection_is_recorded_in_the_queue_wait_histogram(self, translation):
        """A histogram that only sees admitted requests reports 'everyone seated
        instantly' during the exact saturation it exists to measure."""
        metrics = _MetricsRecorder()
        admission = translation.TranslationAdmission(
            max_concurrent=1, queue_wait_seconds=0.05, metrics=metrics
        )
        release, occupied, holders = self._saturate(translation, admission)

        await asyncio.to_thread(occupied.wait, SAFETY_TIMEOUT)
        admitted_waits = len(metrics.waits)

        with pytest.raises(translation.HTTPException):
            await translation.translate(request_with(admission))

        assert metrics.rejections == 1
        assert len(metrics.waits) == admitted_waits + 1, "rejection was not observed"
        assert metrics.waits[-1] >= 0.05

        release.set()
        await asyncio.wait_for(asyncio.gather(*holders), timeout=SAFETY_TIMEOUT)


class TestSlotOwnership:
    """A slot may only be held by work that is actually running."""

    @pytest.mark.asyncio
    async def test_cancelled_request_keeps_its_slot_until_the_thread_finishes(self, translation):
        """asyncio.to_thread cannot interrupt a call it has started. Releasing on
        the awaiting task's finally would hand capacity to the next caller while
        this request's thread was still on the GPU."""
        metrics = _MetricsRecorder()
        admission = translation.TranslationAdmission(
            max_concurrent=1, queue_wait_seconds=5.0, metrics=metrics
        )
        release = threading.Event()
        started = threading.Event()

        def hold(texts, *_args, **_kwargs):
            started.set()
            release.wait(timeout=SAFETY_TIMEOUT)
            return ["translated"]

        translation._translate_texts = hold

        task = asyncio.create_task(translation.translate(request_with(admission)))
        await asyncio.to_thread(started.wait, SAFETY_TIMEOUT)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The thread is still inside hold(), so the slot must still be taken.
        assert admission.in_flight == 1, (
            "the cancelled request released its slot while its worker thread was "
            "still running the pipeline"
        )

        release.set()
        for _ in range(int(SAFETY_TIMEOUT / 0.01)):
            await asyncio.sleep(0.01)
            if admission.in_flight == 0:
                break
        assert admission.in_flight == 0, "the slot was never returned"

    @pytest.mark.asyncio
    async def test_release_survives_a_loop_that_is_already_closed(self, translation):
        """The release runs in a `finally` inside a worker thread. At shutdown the
        loop can already be gone, and raising there would kill the thread for a
        slot nobody is waiting on any more."""
        admission = translation.TranslationAdmission(max_concurrent=1)
        dead_loop = asyncio.new_event_loop()
        dead_loop.close()

        admission._schedule_release(dead_loop)  # must not raise

        # The slot is simply never handed back, which is correct at shutdown.
        assert admission.in_flight == 0


class TestTokenizerSafety:
    """src_lang is mutable shared state; the lock must actually exclude."""

    @pytest.mark.asyncio
    async def test_tokenizer_lock_excludes_concurrent_encoding(self, translation):
        rendezvous: list[bool] = []
        # Two parties, so it can only be satisfied if both threads are inside
        # the tokenizer at the same moment. Under the lock, neither can be.
        barrier = threading.Barrier(2)

        class _Tensor:
            def to(self, _device):
                return self

        class LockProbeTokenizer:
            lang_code_to_id = {"de": 0, "en": 1}

            def __init__(self):
                self.src_lang = None

            def __call__(self, _text, **_kwargs):
                try:
                    barrier.wait(timeout=0.25)
                    rendezvous.append(True)
                except threading.BrokenBarrierError:
                    pass
                return {"input_ids": _Tensor()}

            def get_lang_id(self, lang):
                return self.lang_code_to_id[lang]

            def batch_decode(self, _outputs, skip_special_tokens=True):
                return ["decoded"]

        translation.m2m_tokenizer = LockProbeTokenizer()

        await asyncio.gather(
            asyncio.to_thread(translation._generate_single, "a", "de", "en", {}),
            asyncio.to_thread(translation._generate_single, "b", "de", "en", {}),
        )

        assert rendezvous == [], (
            "two threads were inside the tokenizer at once; the src_lang mutation "
            "in _generate_single is unguarded"
        )


class TestAdmissionWiring:
    """The component is owned by the lifespan, and absent before it runs."""

    @pytest.mark.asyncio
    async def test_lifespan_installs_and_clears_the_admission_component(self, translation):
        app = SimpleNamespace(state=SimpleNamespace())

        async with translation.lifespan(app):
            installed = app.state.translation_admission
            assert isinstance(installed, translation.TranslationAdmission)
            assert installed.max_concurrent == translation.MAX_CONCURRENT_TRANSLATIONS

        assert app.state.translation_admission is None

    @pytest.mark.asyncio
    async def test_settings_come_from_the_environment(self, monkeypatch):
        module = load_translation(
            monkeypatch,
            MAX_CONCURRENT_TRANSLATIONS=3,
            TRANSLATION_QUEUE_WAIT_SECONDS=7.5,
        )

        assert module.MAX_CONCURRENT_TRANSLATIONS == 3
        assert module.TRANSLATION_QUEUE_WAIT_SECONDS == 7.5
        assert module.TranslationAdmission().max_concurrent == 3

    @pytest.mark.asyncio
    async def test_request_without_app_state_runs_unbounded(self, translation):
        """Model-service tests drive translate() with requests that have no app,
        and every route reached before startup is in the same position."""
        recorder = _ThreadRecorder()
        translation._translate_texts = recorder

        class BareRequest:
            query_params: dict = {}

            async def json(self):
                return PAYLOAD

        response = await translation.translate(BareRequest())

        assert response.status_code == 200
        assert recorder.thread_ids and recorder.thread_ids[0] != threading.get_ident()


class TestWireContract:
    """The 503 and its Retry-After have to survive real FastAPI, not just a dict."""

    @pytest.mark.asyncio
    async def test_retry_after_reaches_the_wire(self, monkeypatch):
        import httpx

        module = load_translation(
            monkeypatch,
            MAX_CONCURRENT_TRANSLATIONS=1,
            TRANSLATION_QUEUE_WAIT_SECONDS=0.05,
        )

        release = threading.Event()
        occupied = threading.Barrier(2)

        def hold(texts, *_args, **_kwargs):
            occupied.wait(timeout=SAFETY_TIMEOUT)
            release.wait(timeout=SAFETY_TIMEOUT)
            return ["translated"]

        module._translate_texts = hold

        transport = httpx.ASGITransport(app=module.app)
        async with module.lifespan(module.app):
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
                holder = asyncio.create_task(client.post("/translate", json=PAYLOAD))
                await asyncio.to_thread(occupied.wait, SAFETY_TIMEOUT)

                busy = await client.post("/translate", json=PAYLOAD)

                assert busy.status_code == 503
                assert busy.headers["retry-after"] == "1"
                assert "detail" in busy.json()

                release.set()
                assert (await asyncio.wait_for(holder, timeout=SAFETY_TIMEOUT)).status_code == 200
