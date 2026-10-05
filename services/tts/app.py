"""HTTP front of the TTS service.

Every voice is loaded once at startup (see voices.py); a voice that fails to
load degrades /health and answers 503 for its language instead of silently
falling back to another engine. Nothing is loaded later and nothing is
evicted: the set is one voice per language, and a cold load mid-conversation
would stall a speaker for seconds. What the set costs in VRAM is measured and
held against TTS_VRAM_BUDGET_MIB instead (#224).
"""

import asyncio
import io
import json
import logging
import os
import time
import zlib
from contextlib import asynccontextmanager
from typing import Any, Dict, List, NamedTuple

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, generate_latest

from services.gpu_metrics import collect_gpu_metrics
from services.resource_metrics import (
    append_gpu_signal,
    collect_resource_metrics,
    derive_auto_scaling_signal,
    get_system_stats,
)
from services.tts.mms_engine import MmsSpeaker
from services.tts.piper_engine import load_piper_speaker, parse_device
from services.tts.speech_text import (
    UnspeakableTextError,
    normalize_for_speech,
    split_for_synthesis,
)
from services.tts.voices import VOICES, Voice, voice_dir
from services.tts.vram import MIB, ProcessVram, VramBudget

try:
    import psutil
except ImportError:  # pragma: no cover - provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

logger = logging.getLogger(__name__)

_nvml_initialized = False
AUDIO_WAV_MIME = "audio/wav"
SYNTHESIS_ERROR_RESPONSES = {
    400: {"description": "Invalid synthesis request"},
    500: {"description": "Synthesis failed"},
    503: {"description": "TTS model unavailable"},
}

requests_total = Counter("tts_requests_total", "Total TTS requests")
health_status = Gauge("tts_health_status", "Health status of TTS service")
voice_loaded = Gauge("tts_voice_loaded", "1 while a language's voice is loaded", ["lang", "engine"])
voice_vram_bytes = Gauge(
    "tts_voice_vram_bytes",
    "VRAM the TTS process gained while loading a voice; the first also carries the CUDA context",
    ["lang"],
)
process_vram_bytes = Gauge(
    "tts_process_vram_bytes", "VRAM held by the TTS process on all cards, NaN if unknown"
)
vram_budget_bytes = Gauge("tts_vram_budget_bytes", "TTS_VRAM_BUDGET_MIB in bytes")


class LoadedVoices(NamedTuple):
    speakers: Dict[str, Any]
    errors: Dict[str, str]
    vram_bytes: Dict[str, int]


def _load_speaker(voice: Voice, device: str) -> Any:
    if voice.engine == "piper":
        return load_piper_speaker(voice_dir(voice), device)
    return MmsSpeaker(voice_dir(voice), device)


def load_speakers(device: str, vram: VramBudget) -> LoadedVoices:
    """Load every voice in turn, noting what each added to this process's VRAM.

    The first voice's figure includes the CUDA context.
    """
    loaded = LoadedVoices({}, {}, {})
    for lang, voice in VOICES.items():
        before = vram.read(expect_context=bool(loaded.speakers))
        try:
            loaded.speakers[lang] = _load_speaker(voice, device)
        except Exception as exc:
            logger.exception("TTS voice %s (%s) failed to load", lang, voice.name)
            loaded.errors[lang] = f"{type(exc).__name__}: {exc}"
            continue
        after = vram.read(expect_context=True)
        if before is not None and after is not None:
            loaded.vram_bytes[lang] = max(after - before, 0)
    return loaded


def _configured_device() -> str:
    kind, index = parse_device(os.environ.get("TTS_DEVICE", "cuda"))
    return "cpu" if kind == "cpu" else f"cuda:{index}"


def _positive_int_setting(name: str, default: str) -> int:
    raw = os.environ.get(name, default)
    if not raw.strip().isdigit() or int(raw) < 1:
        raise ValueError(f"{name} must be a whole number of at least 1, not {raw!r}")
    return int(raw)


def _publish_voice_metrics(loaded: LoadedVoices, budget: int) -> None:
    voice_vram_bytes.clear()
    for lang, voice in VOICES.items():
        voice_loaded.labels(lang=lang, engine=voice.engine).set(int(lang in loaded.speakers))
    for lang, held in loaded.vram_bytes.items():
        voice_vram_bytes.labels(lang=lang).set(held)
    vram_budget_bytes.set(budget)


@asynccontextmanager
async def lifespan(app: FastAPI):
    device = _configured_device()
    # Each synthesis briefly needs tens to hundreds of MiB of VRAM on a card
    # shared with ASR, translation and vLLM. On the production card two long
    # requests at once already ran out of memory; one at a time peaked at
    # 1722 MiB. At ~0.1 s per Piper request the queue is cheap.
    slots = _positive_int_setting("TTS_MAX_CONCURRENT_SYNTHESES", "1")
    # On the production card the ten voices hold 1238 MiB after loading and
    # 1464 MiB once each has spoken, flat from then on. A live reading can
    # also catch a synthesis in flight: 1722 MiB at the peak above.
    budget = _positive_int_setting("TTS_VRAM_BUDGET_MIB", "2048") * MIB
    vram = VramBudget(ProcessVram(pynvml, os.getpid()), budget, on_gpu=device != "cpu")
    loaded = await asyncio.to_thread(load_speakers, device, vram)
    vram.voice_bytes, vram.voices_loaded = loaded.vram_bytes, bool(loaded.speakers)
    app.state.speakers, app.state.load_errors = loaded.speakers, loaded.errors
    app.state.vram = vram
    app.state.synthesis_slots = asyncio.Semaphore(slots)
    _publish_voice_metrics(loaded, budget)
    process_vram_bytes.set_function(lambda: _gauge_value(vram.usage()["process_bytes"]))
    yield


app = FastAPI(title="TTS Service", lifespan=lifespan)


def _numpy_audio_to_wav_bytes(audio: Any, sampling_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, sampling_rate, format="WAV")
    return buffer.getvalue()


def _get_system_stats() -> Dict[str, Any]:
    return get_system_stats(psutil)


def _normalize_lang_code(lang: str) -> str:
    normalized_lang = (lang or "").strip().lower()
    if not normalized_lang:
        raise ValueError("Leerer Sprachcode")
    return normalized_lang


def _seed_for_request(session_id: str | None, text: str, debug_info: Dict[str, Any]) -> int:
    # crc32, not hash(): str hashes are salted per process, so a session's MMS
    # voice would change on every restart.
    if session_id:
        debug_info["seed_source"] = "session_id"
        return zlib.crc32(session_id.encode())

    debug_info["seed_source"] = "text_hash"
    return zlib.crc32(text.encode())


def _audio_response(
    audio_bytes: bytes,
    model_name: str,
    lang: str,
    debug_active: bool,
    debug_info: Dict[str, Any],
    *,
    fallback: bool,
) -> Response:
    headers = {
        "X-TTS-Model": model_name,
        "X-TTS-Fallback": "true" if fallback else "false",
        "X-TTS-Language": lang,
    }
    if debug_active:
        # HTTP headers must be latin-1 encodable; ensure_ascii keeps non-ASCII
        # payloads transportable while preserving the debug data structure.
        headers["X-Debug-Info"] = json.dumps(debug_info, ensure_ascii=True, default=str)
    return Response(content=audio_bytes, media_type=AUDIO_WAV_MIME, headers=headers)


def _error_response(
    debug_active: bool,
    debug_info: Dict[str, Any],
    status_code: int,
    *,
    fallback: bool,
    error: str,
) -> JSONResponse:
    content: Dict[str, Any] = {"fallback": fallback, "error": error}
    if debug_active:
        content["debug"] = debug_info
    return JSONResponse(content=content, status_code=status_code)


def _collect_gpu_metrics() -> Dict[str, Any]:
    """Return GPU availability and utilization details for TTS service."""
    global _nvml_initialized
    gpu_info, _nvml_initialized = collect_gpu_metrics(torch, pynvml, _nvml_initialized)
    return gpu_info


def _collect_resource_metrics() -> Dict[str, Any]:
    return collect_resource_metrics(psutil, _collect_gpu_metrics)


def _append_gpu_signal(reasons: List[str], gpu_device: Dict[str, Any], threshold_gpu: int) -> None:
    """Compatibility wrapper for the service-local health helper."""
    append_gpu_signal(reasons, gpu_device, threshold_gpu)


def _derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return derive_auto_scaling_signal(metrics)


def _build_debug_info(text: Any, lang: Any) -> Dict[str, Any]:
    return {
        "input": {"text": text, "lang": lang},
        "output": None,
        "error": None,
        "duration": None,
        "model": None,
        "system": _get_system_stats(),
    }


def _update_duration(debug_info: Dict[str, Any], start: float) -> None:
    debug_info["duration"] = round(time.perf_counter() - start, 3)


def _gauge_value(held: int | None) -> float:
    return float("nan") if held is None else float(held)


def _vram_report(request: Request) -> Dict[str, Any] | None:
    vram = getattr(request.app.state, "vram", None)
    return vram.usage() if vram is not None else None


def _voice_states(request: Request) -> Dict[str, Dict[str, Any]]:
    speakers = getattr(request.app.state, "speakers", {})
    errors = getattr(request.app.state, "load_errors", {})
    return {
        lang: {
            "engine": voice.engine,
            "voice": voice.name,
            "loaded": lang in speakers,
            "device": getattr(speakers.get(lang), "device", None),
            "error": errors.get(lang),
        }
        for lang, voice in VOICES.items()
    }


@app.get("/health")
def health(request: Request):
    voices = _voice_states(request)
    all_loaded = all(entry["loaded"] for entry in voices.values())
    resources = _collect_resource_metrics()
    gpu_info = resources.get("gpu", {})
    gpu_available = gpu_info.get("available", False)
    gpu_errors: List[str] = list(gpu_info.get("errors") or [])
    if not gpu_available and not gpu_errors:
        gpu_errors.append("torch.cuda.is_available()==False")

    health_status.set(1 if all_loaded else 0)
    return {
        "status": "ok" if all_loaded else "degraded",
        "model": any(entry["loaded"] for entry in voices.values()),
        "gpu": gpu_available,
        "gpu_used": any(str(entry["device"]).startswith("cuda") for entry in voices.values()),
        "gpu_error": "; ".join(gpu_errors) if gpu_errors else None,
        "voices": voices,
        "loaded_models": {lang: entry["loaded"] for lang, entry in voices.items()},
        # Over budget is a warning, not "degraded": every voice still works,
        # and tts_health_status 0 would page as TTSServiceDown.
        "vram": _vram_report(request),
        "resources": resources,
        "autoscaling": _derive_auto_scaling_signal(resources),
    }


@app.get("/supported-languages")
def supported_languages():
    return {"languages": sorted(VOICES)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")


async def _synthesize_in_chunks(
    speaker: Any, spoken: str, seed: int, slots: asyncio.Semaphore
) -> tuple[np.ndarray, int] | None:
    """Speak the text piece by piece, taking the GPU slot for each piece.

    Returns None when no piece contains anything the voice can pronounce.
    """
    parts: List[np.ndarray] = []
    sampling_rate = 0
    for chunk in split_for_synthesis(spoken):
        try:
            async with slots:
                audio, sampling_rate = await asyncio.to_thread(speaker.synthesize, chunk, seed)
        except UnspeakableTextError:
            continue
        parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))
    if not parts:
        return None
    return np.concatenate(parts), sampling_rate


@app.post("/synthesize", responses=SYNTHESIS_ERROR_RESPONSES)
async def synthesize(request: Request):
    start = time.perf_counter()
    requests_total.inc()
    try:
        data = await request.json()
    except (ValueError, RecursionError):  # undecodable, or nested too deeply
        data = None
    if not isinstance(data, dict):
        return _error_response(
            False, {}, 400, fallback=False, error="Request body must be a JSON object"
        )
    # A tts_text from an older caller is ignored: voices read their own
    # script, and the MMS engine romanizes Ethiopic itself.
    text = data.get("text")
    lang = data.get("lang", "de")
    debug_active = (
        str(data.get("debug", "false")).lower() == "true"
        or str(request.query_params.get("debug", "false")).lower() == "true"
    )
    debug_info = _build_debug_info(text, lang)

    def fail(status_code: int, error: str, *, fallback: bool = False) -> JSONResponse:
        debug_info["error"] = error
        _update_duration(debug_info, start)
        return _error_response(
            debug_active, debug_info, status_code, fallback=fallback, error=error
        )

    if not isinstance(text, str) or not text.strip():
        return fail(400, "Field 'text' must be a non-empty string")
    try:
        normalized_lang = _normalize_lang_code(lang)
    except ValueError as exc:
        return fail(400, str(exc))
    voice = VOICES.get(normalized_lang)
    if voice is None:
        return fail(400, f"Keine TTS-Stimme für Sprache '{normalized_lang}' konfiguriert.")
    debug_info["model"] = voice.name
    speaker = request.app.state.speakers.get(normalized_lang)
    if speaker is None:
        return fail(503, f"Kein TTS-Modell für Sprache '{normalized_lang}' geladen.", fallback=True)

    spoken = normalize_for_speech(text, normalized_lang, spell_numbers=voice.spell_numbers)
    debug_info["spoken_text"] = spoken
    seed = _seed_for_request(data.get("session_id"), text, debug_info)
    try:
        spoken_audio = await _synthesize_in_chunks(
            speaker, spoken, seed, request.app.state.synthesis_slots
        )
    except Exception as exc:
        # The endpoint's boundary: the exception text and its traceback stay in the
        # server log as a type name, never in the response.
        logger.exception(
            "TTS synthesis failed (%s)",
            type(exc).__name__,
            # Frames only: the message could carry the text being spoken.
            exc_info=(RuntimeError, RuntimeError("Exception details redacted"), exc.__traceback__),
        )
        debug_info["error_type"] = type(exc).__name__
        return fail(500, "TTS fehlgeschlagen")

    if spoken_audio is None:
        return fail(
            400, f"Text enthält nichts, was die Stimme für '{normalized_lang}' sprechen kann."
        )
    debug_info["output"] = AUDIO_WAV_MIME
    _update_duration(debug_info, start)
    return _audio_response(
        _numpy_audio_to_wav_bytes(*spoken_audio),
        voice.name,
        normalized_lang,
        debug_active,
        debug_info,
        fallback=False,
    )
