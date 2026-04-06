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
from typing import Any, Dict, List

import torch
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, generate_latest
from typing_extensions import Annotated

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
    gpu_available = bool(torch.cuda.is_available())
    gpu_info: Dict[str, Any] = {
        "available": gpu_available,
        "device_count": torch.cuda.device_count() if gpu_available else 0,
        "devices": [],
        "errors": [],
    }

    if not gpu_available:
        return gpu_info

    nvml_ready = False
    if pynvml is not None:
        try:
            if not _nvml_initialized:
                pynvml.nvmlInit()
                _nvml_initialized = True
            nvml_ready = True
        except Exception as exc:  # pragma: no cover - hardware specific branch
            gpu_info["errors"].append(f"nvml_init_failed: {exc}")

    for device_idx in range(gpu_info["device_count"]):
        device_data: Dict[str, Any] = {"index": device_idx}
        try:
            props = torch.cuda.get_device_properties(device_idx)
            torch_alloc = torch.cuda.memory_allocated(device_idx)
            torch_reserved = torch.cuda.memory_reserved(device_idx)
            device_data.update(
                {
                    "name": props.name,
                    "total_memory": props.total_memory,
                    "memory_allocated": torch_alloc,
                    "memory_reserved": torch_reserved,
                    "memory_utilization": None,
                    "utilization_percent": None,
                    "temperature_c": None,
                }
            )
            if nvml_ready:
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(device_idx)
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    device_data["memory_utilization"] = (
                        round(mem.used / mem.total * 100, 2) if mem.total else None
                    )
                    device_data["utilization_percent"] = util.gpu
                    device_data["temperature_c"] = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                    device_data["memory_total_nvml"] = mem.total
                    device_data["memory_used_nvml"] = mem.used
                except Exception as exc:  # pragma: no cover - hardware specific branch
                    gpu_info["errors"].append(
                        f"nvml_query_failed_gpu_{device_idx}: {exc}"
                    )
        except Exception as exc:  # pragma: no cover - hardware specific branch
            gpu_info["errors"].append(f"torch_query_failed_gpu_{device_idx}: {exc}")
        gpu_info["devices"].append(device_data)

    return gpu_info


def _collect_resource_metrics() -> Dict[str, Any]:
    """Gather CPU, memory and GPU statistics for health and auto-scaling insights."""
    metrics: Dict[str, Any] = {
        "cpu_percent": None,
        "memory_percent": None,
        "memory_total": None,
        "memory_available": None,
        "gpu": _collect_gpu_metrics(),
    }

    if psutil is not None:
        try:
            metrics["cpu_percent"] = psutil.cpu_percent(interval=None)
            virtual_mem = psutil.virtual_memory()
            metrics["memory_percent"] = virtual_mem.percent
            metrics["memory_total"] = virtual_mem.total
            metrics["memory_available"] = virtual_mem.available
        except Exception as exc:  # pragma: no cover - psutil rarely fails
            metrics["psutil_error"] = str(exc)
    else:
        metrics["psutil_error"] = "psutil_not_installed"

    return metrics


def _derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest a simple scaling action based on current resource pressure."""
    threshold_cpu = 85
    threshold_mem = 85
    threshold_gpu = 85
    reasons: List[str] = []

    cpu_percent = metrics.get("cpu_percent")
    if cpu_percent is not None and cpu_percent >= threshold_cpu:
        reasons.append(f"cpu>={threshold_cpu}")

    mem_percent = metrics.get("memory_percent")
    if mem_percent is not None and mem_percent >= threshold_mem:
        reasons.append(f"memory>={threshold_mem}")

    gpu_info = metrics.get("gpu", {})
    for device in gpu_info.get("devices", []):
        gpu_util = device.get("utilization_percent")
        mem_util = device.get("memory_utilization")
        if gpu_util is not None and gpu_util >= threshold_gpu:
            reasons.append(f"gpu{device.get('index')}_util>={threshold_gpu}")
        if mem_util is not None and mem_util >= threshold_gpu:
            reasons.append(f"gpu{device.get('index')}_mem>={threshold_gpu}")

    recommended_action = "scale_up" if reasons else "steady"

    return {"recommended_action": recommended_action, "reasons": reasons}


def _get_system_stats() -> Dict[str, Any]:
    system_stats = {"cpu": None, "ram": None}
    if psutil is not None:
        try:
            system_stats = {
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
            }
        except Exception:  # pragma: no cover - psutil rarely fails
            system_stats = {"cpu": None, "ram": None}
    return system_stats


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
    lang: Annotated[str, Form("de")],
    request: Request,
    debug: Annotated[str | None, Form(None)] = None,
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
