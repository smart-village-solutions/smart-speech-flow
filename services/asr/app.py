import asyncio
import subprocess


# Hilfsfunktion für ffmpeg-Normalisierung
def normalize_to_wav16k(in_path):
    ffmpeg_bin = os.getenv("FFMPEG_BIN", "ffmpeg")
    enable_loudnorm = os.getenv("NORMALIZE_ENABLE_LOUDNORM", "0") == "1"
    enable_vad = os.getenv("NORMALIZE_ENABLE_VAD", "0") == "1"
    filters = []
    if enable_loudnorm:
        filters.append("loudnorm")
    if enable_vad:
        filters.append("silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB")
    afilter = ",".join(filters) if filters else None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as out_tmp:
        out_path = out_tmp.name
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        in_path,
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
    ]
    if afilter:
        cmd += ["-af", afilter]
    cmd += [out_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, OSError):
        # OSError: no ffmpeg binary. The command line names temporary paths, so the
        # error carries none of it.
        if os.path.exists(out_path):
            os.remove(out_path)
        raise RuntimeError("ffmpeg normalisation failed") from None
    return out_path


def _persist_upload_to_temp(file_obj) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".input") as tmp:
        shutil.copyfileobj(file_obj, tmp)
        return tmp.name


import logging
import os
import shutil
import tempfile
import wave
from typing import Any, Dict

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, generate_latest
from typing_extensions import Annotated

from services.gpu_metrics import collect_gpu_metrics
from services.resource_metrics import (
    collect_resource_metrics,
    derive_auto_scaling_signal,
    get_system_stats,
)

try:
    import whisper
except ImportError:
    whisper = None

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is part of service requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

logger = logging.getLogger(__name__)

_nvml_initialized = False
ASR_MODEL_NAME = "large-v3-turbo"
TRANSCRIBE_ERROR_RESPONSES = {
    400: {"description": "Invalid transcription request"},
    # Not 503: the gateway reads a 503 as load and tells the user to retry, but a
    # missing model is a setup fault that a retry cannot fix.
    500: {"description": "ASR model not loaded, or transcription failed"},
}
# Whisper large-v3-turbo never predicts its no-speech token, not even for digital
# silence, and answers silence and noise with " Vielen Dank." / " Thank you." (#498).
# Only what cannot be speech is kept from it: nothing audible, or a level that never
# moves (hum, hiss). On gateway-normalised clips the flattest speech measured, a 0.6 s
# word at 0 dB SNR, moves 5.0 dB and white hiss 0.8 dB. Fluctuating noise (pink,
# brown, a room) still reaches Whisper: by level alone it overlaps a short noisy word.
SPEECH_FRAME_SECONDS = 0.03
AUDIBLE_DBFS = -60.0
MIN_AUDIBLE_SECONDS = 0.1
MIN_LEVEL_MOVEMENT_DB = 3.0


def _holds_speech(wav_path: str) -> bool:
    """False only for a mono 16-bit WAV that is inaudible or holds one flat level.

    A file this check cannot read counts as speech, so Whisper still decides.
    """
    try:
        with wave.open(wav_path, "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2 or wav.getframerate() <= 0:
                return True
            rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
    except (wave.Error, EOFError):
        return True
    frame_len = max(1, int(rate * SPEECH_FRAME_SECONDS))
    samples = np.frombuffer(pcm, dtype=np.int16, count=len(pcm) // 2)
    count = len(samples) // frame_len
    if count == 0:
        return False
    frames = samples[: count * frame_len].reshape(count, frame_len).astype(np.float32) / 32768
    level_db = 20 * np.log10(np.maximum(np.sqrt(np.mean(np.square(frames), axis=1)), 1e-5))
    audible_seconds = np.count_nonzero(level_db > AUDIBLE_DBFS) * frame_len / rate
    movement_db = level_db.max() - np.percentile(level_db, 10)
    return bool(audible_seconds >= MIN_AUDIBLE_SECONDS and movement_db >= MIN_LEVEL_MOVEMENT_DB)


def _collect_gpu_metrics() -> Dict[str, Any]:
    """Return GPU availability and utilization details if torch can detect devices."""
    global _nvml_initialized
    gpu_info, _nvml_initialized = collect_gpu_metrics(torch, pynvml, _nvml_initialized)
    return gpu_info


def _collect_resource_metrics() -> Dict[str, Any]:
    return collect_resource_metrics(psutil, _collect_gpu_metrics)


def _derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
    return derive_auto_scaling_signal(metrics)


def _get_system_stats() -> Dict[str, Any]:
    return get_system_stats(psutil)


def _build_debug_info(lang: str) -> Dict[str, Any]:
    return {
        "input": {"lang": lang},
        "output": None,
        "error": None,
        "duration": None,
        "model": f"whisper-{ASR_MODEL_NAME}",
        "system": _get_system_stats(),
    }


def _build_asr_response(
    text: str, fallback: bool, debug_active: bool, debug_info: Dict[str, Any]
) -> Dict[str, Any]:
    if debug_active:
        return {"text": text, "fallback": fallback, "debug": debug_info}
    return {"text": text, "fallback": fallback}


app = FastAPI(title="ASR Service")
SUPPORTED_LANGS = ["de", "en", "ar", "tr", "am", "fa", "ru", "uk", "ku", "ti"]
requests_total = Counter("asr_requests_total", "Total ASR requests")
health_status = Gauge("asr_health_status", "Health status of ASR service")


def _load_asr_model():
    if not whisper:
        logger.error("ASR model unavailable: whisper is not installed")
        return None
    try:
        return whisper.load_model(
            ASR_MODEL_NAME, device="cuda" if torch.cuda.is_available() else "cpu"
        )
    except Exception:
        # The service still starts, so /health can report it degraded; /transcribe
        # then answers 500 rather than a transcript.
        logger.exception("ASR model %s failed to load", ASR_MODEL_NAME)
        return None


model = _load_asr_model()
model_loaded = model is not None


@app.get("/health")
def health():
    model_available = model_loaded
    resources = _collect_resource_metrics()
    autoscaling = _derive_auto_scaling_signal(resources)
    health_status.set(1 if model_available else 0)
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "resources": resources,
        "autoscaling": autoscaling,
    }


@app.get("/supported-languages")
def supported_languages():
    """Return list of supported languages"""
    return {"languages": SUPPORTED_LANGS}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")


@app.post("/transcribe", responses=TRANSCRIBE_ERROR_RESPONSES)
async def transcribe(
    file: Annotated[UploadFile, File(...)],
    request: Request,
    lang: Annotated[str, Form()] = "de",
    debug: Annotated[str | None, Form()] = None,
):
    import time

    start = time.perf_counter()
    # Debug-Parameter aus Query und Form lesen
    debug_query = request.query_params.get("debug") if request else None
    debug_active = (str(debug).lower() == "true") or (str(debug_query).lower() == "true")
    requests_total.inc()
    debug_info = _build_debug_info(lang)
    if lang not in SUPPORTED_LANGS:
        debug_info["error"] = f"Unsupported language code: {lang}"
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        raise HTTPException(status_code=400, detail=f"Unsupported language code: {lang}")
    if not model_loaded:
        raise HTTPException(status_code=500, detail="ASR model not loaded")
    # Speichere die Audiodatei temporär
    tmp_path = await asyncio.to_thread(_persist_upload_to_temp, file.file)
    norm_path = None
    try:
        norm_path = await asyncio.to_thread(normalize_to_wav16k, tmp_path)
        if await asyncio.to_thread(_holds_speech, norm_path):
            result = await asyncio.to_thread(model.transcribe, norm_path, language=lang)
            text = result.get("text", "")
        else:
            # An empty transcript is what makes the gateway answer NO_SPEECH_RECOGNIZED.
            logger.info("No speech in the recording; Whisper skipped")
            text = ""
        debug_info["output"] = text
    except Exception as e:
        # Answering with a stand-in text made the gateway translate and speak it.
        logger.exception(
            "Transcription failed (%s)",
            type(e).__name__,
            # Frames only, as for every other failure this service logs.
            exc_info=(RuntimeError, RuntimeError("Exception details redacted"), e.__traceback__),
        )
        raise HTTPException(status_code=500, detail="Transcription failed") from None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if norm_path and os.path.exists(norm_path):
            os.remove(norm_path)
    debug_info["duration"] = round(time.perf_counter() - start, 3)
    return _build_asr_response(text, False, debug_active, debug_info)
