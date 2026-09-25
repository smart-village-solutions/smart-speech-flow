"""HTTP front of the TTS service.

Every voice is loaded once at startup (see voices.py); a voice that fails to
load degrades /health and answers 503 for its language instead of silently
falling back to another engine.
"""

import asyncio
import io
import json
import logging
import os
import time
import traceback
from contextlib import asynccontextmanager
from typing import Any, Dict, List

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
from services.tts.piper_engine import load_piper_speaker
from services.tts.speech_text import UnspeakableTextError, normalize_for_speech
from services.tts.voices import VOICES, Voice, voice_dir

try:
    import psutil
except ImportError:  # pragma: no cover - provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

logger = logging.getLogger(__name__)

DEVICE = os.environ.get("TTS_DEVICE", "cuda")
_nvml_initialized = False
AUDIO_WAV_MIME = "audio/wav"
SYNTHESIS_ERROR_RESPONSES = {
    400: {"description": "Invalid synthesis request"},
    500: {"description": "Synthesis failed"},
    503: {"description": "TTS model unavailable"},
}

requests_total = Counter("tts_requests_total", "Total TTS requests")
health_status = Gauge("tts_health_status", "Health status of TTS service")


def _load_speaker(voice: Voice, device: str) -> Any:
    if voice.engine == "piper":
        return load_piper_speaker(voice_dir(voice), device)
    return MmsSpeaker(voice_dir(voice), device)


def load_speakers(device: str) -> tuple[Dict[str, Any], Dict[str, str]]:
    speakers: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for lang, voice in VOICES.items():
        try:
            speakers[lang] = _load_speaker(voice, device)
        except Exception as exc:
            logger.exception("TTS voice %s (%s) failed to load", lang, voice.name)
            errors[lang] = f"{type(exc).__name__}: {exc}"
    return speakers, errors


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.speakers, app.state.load_errors = await asyncio.to_thread(load_speakers, DEVICE)
    # Each synthesis briefly needs tens to hundreds of MiB of VRAM on a card
    # shared with ASR, translation and vLLM. On the production card two long
    # requests at once already ran out of memory; one at a time peaked at
    # 1722 MiB. At ~0.1 s per Piper request the queue is cheap.
    app.state.synthesis_slots = asyncio.Semaphore(
        int(os.environ.get("TTS_MAX_CONCURRENT_SYNTHESES", "1"))
    )
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
    if session_id:
        debug_info["seed_source"] = "session_id"
        return hash(session_id) % (2**32)

    debug_info["seed_source"] = "text_hash"
    return hash(text) % (2**32)


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
        "gpu_used": any(entry["device"] == "cuda" for entry in voices.values()),
        "gpu_error": "; ".join(gpu_errors) if gpu_errors else None,
        "voices": voices,
        "loaded_models": {lang: entry["loaded"] for lang, entry in voices.items()},
        "resources": resources,
        "autoscaling": _derive_auto_scaling_signal(resources),
    }


@app.get("/supported-languages")
def supported_languages():
    return {"languages": sorted(VOICES)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")


@app.post("/synthesize", responses=SYNTHESIS_ERROR_RESPONSES)
async def synthesize(request: Request):
    start = time.perf_counter()
    requests_total.inc()
    data = await request.json()
    # tts_text is the translation service's romanization. Voices read their
    # own script, and the MMS tokenizers romanize Ethiopic themselves.
    text = data.get("text", "Hallo Welt")
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
        async with request.app.state.synthesis_slots:
            audio, sampling_rate = await asyncio.to_thread(speaker.synthesize, spoken, seed)
    except UnspeakableTextError:
        return fail(
            400, f"Text enthält nichts, was die Stimme für '{normalized_lang}' sprechen kann."
        )
    except Exception as exc:
        debug_info["traceback"] = traceback.format_exc()
        return fail(500, f"TTS fehlgeschlagen: {exc}")

    debug_info["output"] = AUDIO_WAV_MIME
    _update_duration(debug_info, start)
    return _audio_response(
        _numpy_audio_to_wav_bytes(audio, sampling_rate),
        voice.name,
        normalized_lang,
        debug_active,
        debug_info,
        fallback=False,
    )
