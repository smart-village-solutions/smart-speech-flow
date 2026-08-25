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
        filters.append(
            "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB"
        )
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
    except Exception as e:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise RuntimeError(f"ffmpeg-Normalisierung fehlgeschlagen: {e}")
    return out_path


def _persist_upload_to_temp(file_obj) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".input") as tmp:
        shutil.copyfileobj(file_obj, tmp)
        return tmp.name


import os
import shutil
import tempfile
from typing import Any, Dict

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

_nvml_initialized = False
TRANSCRIBE_ERROR_RESPONSES = {
    400: {"description": "Invalid transcription request"},
    503: {"description": "ASR model unavailable"},
}


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
        "model": "whisper-base",
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
model = None
model_loaded = False
if whisper:
    try:
        model = whisper.load_model(
            "base", device="cuda" if torch.cuda.is_available() else "cpu"
        )
        model_loaded = True
    except Exception:
        model = None
        model_loaded = False


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
    debug_active = (str(debug).lower() == "true") or (
        str(debug_query).lower() == "true"
    )
    requests_total.inc()
    debug_info = _build_debug_info(lang)
    if lang not in SUPPORTED_LANGS:
        debug_info["error"] = f"Unsupported language code: {lang}"
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        raise HTTPException(
            status_code=400, detail=f"Unsupported language code: {lang}"
        )
    if not model_loaded:
        debug_info["error"] = "ASR-Modell nicht geladen"
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        return _build_asr_response("Hallo Welt", True, debug_active, debug_info)
    # Speichere die Audiodatei temporär
    tmp_path = await asyncio.to_thread(_persist_upload_to_temp, file.file)
    norm_path = None
    try:
        norm_path = await asyncio.to_thread(normalize_to_wav16k, tmp_path)
        result = await asyncio.to_thread(model.transcribe, norm_path, language=lang)
        text = result.get("text", "")
        debug_info["output"] = text
    except Exception as e:
        text = "Fehler bei der Transkription"
        debug_info["error"] = str(e)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if norm_path and os.path.exists(norm_path):
            os.remove(norm_path)
    debug_info["duration"] = round(time.perf_counter() - start, 3)
    return _build_asr_response(text, False, debug_active, debug_info)
