import asyncio
import logging
import math
import os
import re
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from services.gpu_metrics import collect_gpu_metrics
from services.resource_metrics import (
    collect_resource_metrics,
    derive_auto_scaling_signal,
    get_system_stats,
)

try:
    import psutil
except ImportError:  # pragma: no cover - dependency provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

logger = logging.getLogger(__name__)

_nvml_initialized = False
TRANSLATION_ERROR_RESPONSES = {
    400: {"description": "Invalid translation request"},
    500: {"description": "Translation failed"},
    503: {
        "description": (
            "Translation model unavailable, or no inference slot became available "
            "within the configured queue wait. The latter carries a Retry-After header."
        )
    },
}


def _get_system_stats() -> Dict[str, Any]:
    return get_system_stats(psutil)


def _build_debug_response(
    debug_active: bool, debug_info: Dict[str, Any], status_code: int
) -> JSONResponse | None:
    if not debug_active:
        return None
    return JSONResponse(
        {"translations": None, "debug": debug_info}, status_code=status_code
    )


class _DebugResponse(Exception):
    def __init__(self, response: JSONResponse):
        self.response = response


def _raise_http_error(
    debug_active: bool, debug_info: Dict[str, Any], status_code: int, detail: str
) -> None:
    debug_info["error"] = detail
    debug_response = _build_debug_response(debug_active, debug_info, status_code)
    if debug_response is not None:
        raise _DebugResponse(debug_response)
    raise HTTPException(status_code=status_code, detail=detail)


def _collect_gpu_metrics() -> Dict[str, Any]:
    """Return GPU availability and utilization details if devices are present."""
    global _nvml_initialized
    gpu_info, _nvml_initialized = collect_gpu_metrics(torch, pynvml, _nvml_initialized)
    return gpu_info


def _collect_resource_metrics() -> Dict[str, Any]:
    return collect_resource_metrics(psutil, _collect_gpu_metrics)


def _derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return derive_auto_scaling_signal(metrics)


try:
    from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
except ImportError:
    M2M100ForConditionalGeneration = None
    M2M100Tokenizer = None

# ----------------------------
# Config
# ----------------------------
MODEL_NAME = os.getenv(
    "MODEL_NAME", "facebook/m2m100_1.2B"
)  # oder "facebook/m2m100_418M"
PREFER_FP16 = os.getenv("PREFER_FP16", "1") == "1"  # FP16 nur auf GPU
DEVICE_STR = os.getenv("DEVICE", "cuda:0" if torch.cuda.is_available() else "cpu")

# Generierungs-Defaults
GEN_MAX_NEW_TOKENS = int(os.getenv("GEN_MAX_NEW_TOKENS", "256"))
GEN_NUM_BEAMS = int(os.getenv("GEN_NUM_BEAMS", "5"))
GEN_LENGTH_PENALTY = float(os.getenv("GEN_LENGTH_PENALTY", "1.0"))
GEN_EARLY_STOPPING = os.getenv("GEN_EARLY_STOPPING", "1") == "1"

# Input-Limits
MAX_INPUT_TOKENS = int(os.getenv("MAX_INPUT_TOKENS", "1024"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "20000"))  # rudimentäres Schutzlimit
DENY_EMPTY = os.getenv("DENY_EMPTY", "1") == "1"

# ----------------------------
# Inference admission control
# ----------------------------
# Matches the gateway's MAX_CONCURRENT_PIPELINES so this service is not a
# tighter chokepoint than the system-level boundary. Exactly 0 disables the
# bound. The figure is inferred from the hardware — one RTX 4000 Ada shared by
# ASR, translation and TTS, one M2M100 instance here — not measured; the metrics
# below exist so load tests can raise it.
DEFAULT_MAX_CONCURRENT_TRANSLATIONS = 2
# Under the gateway's 30s HTTP timeout for /translate, so a saturated queue
# answers with an attributable 503 rather than leaving the caller to time out.
DEFAULT_TRANSLATION_QUEUE_WAIT_SECONDS = 25.0

MAX_CONCURRENT_TRANSLATIONS = int(
    os.getenv("MAX_CONCURRENT_TRANSLATIONS", str(DEFAULT_MAX_CONCURRENT_TRANSLATIONS))
)
TRANSLATION_QUEUE_WAIT_SECONDS = float(
    os.getenv("TRANSLATION_QUEUE_WAIT_SECONDS", str(DEFAULT_TRANSLATION_QUEUE_WAIT_SECONDS))
)

# Spread across the plausible wait range: most requests should be seated
# immediately, and anything near the timeout is a capacity signal.
QUEUE_WAIT_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 25.0, float("inf"))


class TranslationBusyError(RuntimeError):
    """Raised when no inference slot came free within the configured wait."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        queue_wait_seconds: float,
        waited_seconds: float,
    ) -> None:
        super().__init__(
            f"No inference slot available within {queue_wait_seconds:.2f}s "
            f"(limit {max_concurrent})"
        )
        self.max_concurrent = max_concurrent
        self.queue_wait_seconds = queue_wait_seconds
        self.waited_seconds = waited_seconds
        # Whole seconds and never below one, so a client reading the header and a
        # client reading the message wait the same amount of time.
        self.retry_after_seconds = max(1, math.ceil(queue_wait_seconds))

    @property
    def retry_after_header(self) -> str:
        return str(self.retry_after_seconds)


@dataclass(frozen=True)
class TranslationAdmissionMetrics:
    """The three series admission control reports on, injectable for tests."""

    in_flight: Any
    queue_wait: Any
    rejected: Any


class TranslationAdmission:
    """Bounds concurrent GPU inference and keeps the event loop free.

    ``run()`` is the sole entry point. The inference functions are synchronous
    and execute on a worker thread, and ``asyncio.to_thread`` cannot interrupt a
    call it has started; if the slot were released by the awaiting task instead,
    a disconnected request would hand its capacity to the next caller while its
    own thread was still on the GPU, and real concurrency could exceed the limit.
    """

    def __init__(
        self,
        max_concurrent: Optional[int] = None,
        queue_wait_seconds: Optional[float] = None,
        *,
        metrics: Optional[Any] = None,
    ) -> None:
        limit = MAX_CONCURRENT_TRANSLATIONS if max_concurrent is None else max_concurrent
        wait = TRANSLATION_QUEUE_WAIT_SECONDS if queue_wait_seconds is None else queue_wait_seconds

        # A negative limit is a typo, not a request to run unbounded, and
        # silently removing the bound is the dangerous reading of it. Only an
        # explicit 0 disables.
        if limit < 0:
            logger.warning(
                "MAX_CONCURRENT_TRANSLATIONS=%s is negative; using default %s. "
                "Set exactly 0 to disable the bound.",
                limit,
                DEFAULT_MAX_CONCURRENT_TRANSLATIONS,
            )
            limit = DEFAULT_MAX_CONCURRENT_TRANSLATIONS

        if wait <= 0:
            logger.warning(
                "TRANSLATION_QUEUE_WAIT_SECONDS=%s is not positive; using default %s.",
                wait,
                DEFAULT_TRANSLATION_QUEUE_WAIT_SECONDS,
            )
            wait = DEFAULT_TRANSLATION_QUEUE_WAIT_SECONDS

        self.max_concurrent = limit
        self.queue_wait_seconds = wait
        self._metrics = metrics if metrics is not None else _admission_metrics()
        self._in_flight = 0
        # Sized once, so the limit cannot drift from the configuration it was
        # built with.
        self._semaphore = asyncio.Semaphore(max(1, limit))

    @property
    def enabled(self) -> bool:
        return self.max_concurrent > 0

    @property
    def in_flight(self) -> int:
        return self._in_flight

    async def run(self, func: Callable[..., List[str]], /, *args: Any, **kwargs: Any) -> List[str]:
        """Runs a synchronous inference function on a worker thread under the bound.

        Raises ``TranslationBusyError`` if no slot comes free within the
        configured wait.
        """
        if not self.enabled:
            return await asyncio.to_thread(func, *args, **kwargs)

        await self._acquire()
        loop = asyncio.get_running_loop()

        def guarded() -> List[str]:
            try:
                return func(*args, **kwargs)
            finally:
                # Released from inside the worker thread, so the slot tracks the
                # inference's real lifetime rather than the awaiting task's.
                self._schedule_release(loop)

        return await asyncio.to_thread(guarded)

    def _schedule_release(self, loop: asyncio.AbstractEventLoop) -> None:
        """Hands the slot back on the loop thread.

        The semaphore is not thread-safe, so the release is marshalled out of the
        worker thread. This runs in a ``finally`` inside that thread and must
        never raise: at shutdown the loop can already be gone, and by then there
        is no capacity left to account for.
        """
        try:
            loop.call_soon_threadsafe(self._release)
        except RuntimeError:
            logger.debug("Event loop closed before inference slot release")

    async def _acquire(self) -> None:
        started = time.perf_counter()
        try:
            # Python 3.11+ returns the permit if the waiter is cancelled, so a
            # timeout here cannot leak capacity.
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_wait_seconds)
        except TimeoutError:
            # Observed on the rejection path too: a histogram that only sees
            # admitted requests reports "everyone seated instantly" during the
            # very saturation it exists to measure.
            waited = time.perf_counter() - started
            self._observe_wait(waited)
            self._metrics.rejected.inc()
            raise TranslationBusyError(
                max_concurrent=self.max_concurrent,
                queue_wait_seconds=self.queue_wait_seconds,
                waited_seconds=waited,
            ) from None

        self._in_flight += 1
        self._metrics.in_flight.inc()
        self._observe_wait(time.perf_counter() - started)

    def _observe_wait(self, waited: float) -> None:
        self._metrics.queue_wait.observe(waited)

    def _release(self) -> None:
        self._semaphore.release()
        self._in_flight -= 1
        self._metrics.in_flight.dec()


def _resolve_admission(request: Any) -> Optional[TranslationAdmission]:
    """The app's admission component, or ``None`` when there isn't one.

    The isinstance check is load-bearing: this handler is also driven directly
    with fake requests that have no ``app``, where attribute access invents a
    truthy object rather than raising. Unbounded offload is the right answer
    there, and for any request reached before lifespan startup.
    """
    state = getattr(getattr(request, "app", None), "state", None)
    candidate = getattr(state, "translation_admission", None)
    return candidate if isinstance(candidate, TranslationAdmission) else None


# ----------------------------
# App & Metrics
# ----------------------------
requests_total = Counter("translation_requests_total", "Total translation requests")
errors_total = Counter("translation_errors_total", "Total translation errors")
tokens_generated_total = Counter(
    "translation_tokens_generated_total", "Total tokens generated"
)
health_status = Gauge(
    "translation_health_status", "Health status of Translation service"
)  # 1 ok, 0 degraded
request_latency = Histogram(
    "translation_request_latency_seconds",
    "Latency of translation requests",
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 4, 8, 16, 32),
)
translation_in_flight = Gauge(
    "translation_in_flight", "Translations currently holding an inference slot"
)
translation_queue_wait_seconds = Histogram(
    "translation_queue_wait_seconds",
    "Time a request waited for an inference slot, admitted or rejected",
    buckets=QUEUE_WAIT_BUCKETS,
)
translation_rejected_total = Counter(
    "translation_rejected_total",
    "Requests rejected because no inference slot came free",
)


def _admission_metrics() -> TranslationAdmissionMetrics:
    return TranslationAdmissionMetrics(
        in_flight=translation_in_flight,
        queue_wait=translation_queue_wait_seconds,
        rejected=translation_rejected_total,
    )


@asynccontextmanager
async def lifespan(app_: Any):
    """Owns the admission component for the life of the running app.

    Built here rather than at import so the semaphore belongs to the loop that
    will actually serve requests, and so tests can construct their own.
    """
    app_.state.translation_admission = TranslationAdmission()
    logger.info(
        "Translation admission control active: limit=%s queue_wait=%ss",
        MAX_CONCURRENT_TRANSLATIONS,
        TRANSLATION_QUEUE_WAIT_SECONDS,
    )
    try:
        yield
    finally:
        app_.state.translation_admission = None


app = FastAPI(title="Translation Service (M2M100)", lifespan=lifespan)

# ----------------------------
# Model Loading
# ----------------------------
m2m_model = None
m2m_tokenizer = None
tokenizer_lock = threading.Lock()
device = torch.device(
    DEVICE_STR if torch.cuda.is_available() or DEVICE_STR.startswith("cpu") else "cpu"
)
dtype = torch.float16 if (device.type == "cuda" and PREFER_FP16) else torch.float32

model_loaded = False
load_error = None
supported_langs: List[str] = []

if M2M100ForConditionalGeneration and M2M100Tokenizer:
    try:
        print(f"Loading model: {MODEL_NAME} on {device} (dtype={dtype})")
        m2m_tokenizer = M2M100Tokenizer.from_pretrained(MODEL_NAME)
        m2m_model = M2M100ForConditionalGeneration.from_pretrained(
            MODEL_NAME, torch_dtype=dtype
        )
        m2m_model.to(device)
        m2m_model.eval()
        model_loaded = True
        supported_langs = sorted(m2m_tokenizer.lang_code_to_id.keys())
        print(
            f"Loaded. Supported langs ({len(supported_langs)}): {', '.join(supported_langs[:10])} ..."
        )
    except Exception as e:
        load_error = str(e)
        print("Error loading M2M100:", e)
        model_loaded = False
else:
    load_error = "transformers not installed"
    print("transformers not installed or import failed")

# ----------------------------
# Utils
# ----------------------------
_SENT_SPLIT = re.compile(r"(?<=[\.!?。？！])\s+")


def _validate_lang(code: str) -> None:
    if not m2m_tokenizer:
        raise HTTPException(status_code=503, detail="Tokenizer unavailable")
    if code not in m2m_tokenizer.lang_code_to_id:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language code '{code}'. Use one of: {', '.join(supported_langs)}",
        )


def _as_list(text: str | List[str]) -> List[str]:
    if isinstance(text, list):
        return [str(t) for t in text]
    return [str(text)]


def _chunk_text_if_needed(text: str) -> List[str]:
    """Sehr einfache, satzbasierte Chunking-Strategie, falls Token-Limit überschritten würde."""
    # Schneller Check über Zeichenlänge
    if len(text) <= MAX_INPUT_CHARS:
        return [text]

    parts = _SENT_SPLIT.split(text)
    chunks, current = [], ""

    for p in parts:
        # grob packen; Feinschnitt passiert später via Tokenizer-Truncation-Check
        candidate = (current + " " + p).strip() if current else p
        if len(candidate) > MAX_INPUT_CHARS // 4 and current:
            chunks.append(current)
            current = p
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def _translate_texts(
    texts: List[str],
    source_lang: str,
    target_lang: str,
    gen_overrides: Dict[str, Any],
) -> List[str]:
    outputs: List[str] = []
    for text in texts:
        if len(text) > MAX_INPUT_CHARS:
            chunks = _chunk_text_if_needed(text)
            partials = [
                _generate_single(chunk, source_lang, target_lang, gen_overrides)
                for chunk in chunks
            ]
            outputs.append(" ".join(partials))
        else:
            outputs.append(
                _generate_single(text, source_lang, target_lang, gen_overrides)
            )
    return outputs


async def _run_inference_off_loop(
    request: Any,
    texts: List[str],
    source_lang: str,
    target_lang: str,
    gen_overrides: Dict[str, Any],
) -> List[str]:
    """Runs blocking M2M100 inference on a worker thread, under the service bound.

    Without an admission component the offload still happens: keeping the event
    loop free is the point, and bounding is the defence that comes with it.
    """
    admission = _resolve_admission(request)
    if admission is None:
        return await asyncio.to_thread(
            _translate_texts, texts, source_lang, target_lang, gen_overrides
        )

    return await admission.run(_translate_texts, texts, source_lang, target_lang, gen_overrides)


def _busy_response(
    busy: TranslationBusyError, *, debug_active: bool, debug_info: Dict[str, Any]
) -> JSONResponse:
    """503 for a saturated inference queue, carrying Retry-After.

    Returns the debug envelope when debug is active and raises otherwise, rather
    than going through ``_raise_http_error``: that one cannot attach headers, and
    a Retry-After the client never receives is not a contract.
    """
    detail = (
        f"Translation service busy: no inference slot became available within "
        f"{busy.queue_wait_seconds:.1f}s (limit {busy.max_concurrent})"
    )
    debug_info["error"] = detail
    debug_response = _build_debug_response(debug_active, debug_info, 503)
    if debug_response is None:
        raise HTTPException(
            status_code=503,
            detail=detail,
            headers={"Retry-After": busy.retry_after_header},
        )

    debug_response.headers["retry-after"] = busy.retry_after_header
    return debug_response


def _maybe_uromanize(outputs: List[str], expect_list: bool) -> str | List[str] | None:
    try:
        from uroman import uromanize

        romanized = [uromanize(output) for output in outputs]
        return romanized if expect_list else romanized[0]
    except ImportError:
        return None


def _generate_single(
    text: str, source_lang: str, target_lang: str, gen_overrides: Dict[str, Any]
) -> str:
    # Nebenläufigkeit: src_lang ist mutable → Lock
    with tokenizer_lock:
        m2m_tokenizer.src_lang = source_lang
        encoded = m2m_tokenizer(
            text, return_tensors="pt", truncation=True, max_length=MAX_INPUT_TOKENS
        )

    # Tensors auf dasselbe Gerät
    encoded = {k: v.to(device) for k, v in encoded.items()}

    forced_bos_id = m2m_tokenizer.get_lang_id(target_lang)

    # Generierungsparameter zusammenführen
    gen_kwargs = {
        "forced_bos_token_id": forced_bos_id,
        "max_new_tokens": GEN_MAX_NEW_TOKENS,
        "num_beams": GEN_NUM_BEAMS,
        "length_penalty": GEN_LENGTH_PENALTY,
        "early_stopping": GEN_EARLY_STOPPING,
    }
    if gen_overrides:
        gen_kwargs.update(gen_overrides)

    # Inference
    with torch.inference_mode():
        outputs = m2m_model.generate(**encoded, **gen_kwargs)

    # Metriken: generierte Tokens schätzen
    try:
        tokens_generated_total.inc(int(outputs.shape[-1]))
    except Exception:
        pass

    return m2m_tokenizer.batch_decode(outputs, skip_special_tokens=True)[0]


# ----------------------------
# Routes
# ----------------------------
@app.get("/health")
def health():
    ok = bool(model_loaded)
    resources = _collect_resource_metrics()
    autoscaling = _derive_auto_scaling_signal(resources)
    health_status.set(1 if ok else 0)
    return {
        "status": "ok" if ok else "degraded",
        "model_loaded": ok,
        "model_name": MODEL_NAME,
        "device": str(device),
        "dtype": "fp16" if dtype == torch.float16 else "fp32",
        "gpu": resources.get("gpu", {}).get("available", False),
        "error": load_error,
        "supported_languages": len(supported_langs),
        "resources": resources,
        "autoscaling": autoscaling,
    }


@app.get("/languages", responses={503: {"description": "Model not loaded"}})
def languages():
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {
        "languages": supported_langs,
        "count": len(supported_langs),
        "model": MODEL_NAME,
    }


@app.get("/metrics")
def metrics():
    return Response(
        generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )


def _parse_translation_payload(
    request_payload: Dict[str, Any], request: Request
) -> tuple[bool, Dict[str, Any]]:
    debug_active = (
        str(request_payload.get("debug", "false")).lower() == "true"
        or str(request.query_params.get("debug", "false")).lower() == "true"
    )
    return debug_active, request_payload


def _validate_translation_input(
    text_in: Any,
    source_lang: Any,
    target_lang: Any,
    *,
    debug_active: bool,
    debug_info: Dict[str, Any],
) -> None:
    if not model_loaded or m2m_model is None or m2m_tokenizer is None:
        _raise_http_error(debug_active, debug_info, 503, "Model unavailable")

    if text_in is None or (
        DENY_EMPTY and isinstance(text_in, str) and not text_in.strip()
    ):
        errors_total.inc()
        _raise_http_error(
            debug_active,
            debug_info,
            400,
            "Field 'text' must be a non-empty string or list of strings",
        )

    if not source_lang or not target_lang:
        errors_total.inc()
        _raise_http_error(
            debug_active,
            debug_info,
            400,
            "Fields 'source_lang' and 'target_lang' are required",
        )

    try:
        _validate_lang(source_lang)
        _validate_lang(target_lang)
    except HTTPException as exc:
        _raise_http_error(debug_active, debug_info, exc.status_code, str(exc.detail))


def _build_translation_response(
    outputs: List[str],
    source_lang: str,
    target_lang: str,
    elapsed: float,
    expect_list: bool,
    debug_active: bool,
    debug_info: Dict[str, Any],
) -> JSONResponse:
    translations = outputs if expect_list else outputs[0]
    debug_info["output"] = translations
    debug_info["duration"] = round(elapsed, 3)
    debug_info["error"] = None
    try:
        request_latency.observe(elapsed)
    except Exception:
        pass
    response = {
        "model": MODEL_NAME,
        "device": str(device),
        "dtype": "fp16" if dtype == torch.float16 else "fp32",
        "source_lang": source_lang,
        "target_lang": target_lang,
        "count": len(outputs),
        "elapsed_seconds": round(elapsed, 3),
        "translations": translations,
        "tts_text": _maybe_uromanize(outputs, expect_list),
    }
    if debug_active:
        response["debug"] = debug_info
    return JSONResponse(response)


@app.post("/translate", responses=TRANSLATION_ERROR_RESPONSES)
async def translate(request: Request):
    debug_active = False
    debug_info = {
        "input": None,
        "output": None,
        "error": None,
        "duration": None,
        "model": MODEL_NAME,
        "system": _get_system_stats(),
    }
    try:
        payload = await request.json()
        debug_active, payload = _parse_translation_payload(payload, request)
    except Exception:
        errors_total.inc()
        try:
            _raise_http_error(debug_active, debug_info, 400, "Invalid JSON payload")
        except _DebugResponse as exc:
            return exc.response

    text_in = payload.get("text")
    source_lang = payload.get("source_lang")
    target_lang = payload.get("target_lang")
    gen_overrides = payload.get("generation", {})
    expect_list = isinstance(text_in, list)
    debug_info["input"] = {
        "text": text_in,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "generation": gen_overrides,
    }

    try:
        _validate_translation_input(
            text_in,
            source_lang,
            target_lang,
            debug_active=debug_active,
            debug_info=debug_info,
        )
    except _DebugResponse as exc:
        return exc.response

    texts = _as_list(text_in)
    start = time.perf_counter()

    try:
        outputs = await _run_inference_off_loop(
            request, texts, source_lang, target_lang, gen_overrides
        )
        elapsed = time.perf_counter() - start
        return _build_translation_response(
            outputs,
            source_lang,
            target_lang,
            elapsed,
            expect_list,
            debug_active,
            debug_info,
        )
    except TranslationBusyError as busy:
        # Ahead of `except Exception`, which would otherwise turn a capacity
        # rejection into a 500 "Translation failed".
        return _busy_response(busy, debug_active=debug_active, debug_info=debug_info)
    except HTTPException as exc:
        try:
            _raise_http_error(
                debug_active, debug_info, exc.status_code, str(exc.detail)
            )
        except _DebugResponse as debug_response:
            return debug_response.response
        raise
    except Exception as e:
        errors_total.inc()
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        try:
            _raise_http_error(debug_active, debug_info, 500, f"Translation failed: {e}")
        except _DebugResponse as exc:
            return exc.response
        raise
