import asyncio
import io
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List

import soundfile as sf
import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, generate_latest
from transformers import pipeline

try:
    from TTS.api import TTS

    TTSApi = TTS
except ImportError:
    TTSApi = None

try:
    import psutil
except ImportError:  # pragma: no cover - provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

device = "cuda" if torch.cuda.is_available() else "cpu"
_nvml_initialized = False
AUDIO_WAV_MIME = "audio/wav"
SYNTHESIS_ERROR_RESPONSES = {
    400: {"description": "Invalid synthesis request"},
    500: {"description": "Synthesis failed"},
    503: {"description": "TTS model unavailable"},
}

app = FastAPI(title="TTS Service")
requests_total = Counter("tts_requests_total", "Total TTS requests")
health_status = Gauge("tts_health_status", "Health status of TTS service")
MODEL_PATH = "/models/tts_model.pt"

# Primäre, konkret verifizierte Coqui-Modelle aus deiner Liste/Umgebung
tts_models = {
    "de": "tts_models/de/thorsten/vits",
    "en": "tts_models/en/ljspeech/vits",
    "tr": "tts_models/tr/common-voice/glow-tts",
    "fa": "tts_models/fa/custom/glow-tts",
    "uk": "tts_models/uk/mai/vits",
}

# Mapping ISO-639-1 -> ISO-639-3 für HuggingFace MMS-TTS
iso1_to_iso3_hf = {
    "de": "deu",
    "en": "eng",
    "ar": "ara",
    "tr": "tur",
    "ru": "rus",
    "uk": "ukr",
    "am": "amh",
    "ti": "tir",
    "ku": "kmr",
    "fa": "fas",
}

tts_model_cache = {}


def _coqui_tts_to_audio_bytes(tts_model: Any, text: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "tts-output.wav"
        tts_model.tts_to_file(text=text, file_path=str(tmp_path))
        return tmp_path.read_bytes()


def _numpy_audio_to_wav_bytes(audio: Any, sampling_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, audio, sampling_rate, format="WAV")
    return buffer.getvalue()


def _get_system_stats() -> Dict[str, Any]:
    if psutil is None:
        return {"cpu": None, "ram": None}

    try:
        return {
            "cpu": psutil.cpu_percent(),
            "ram": psutil.virtual_memory().percent,
        }
    except Exception:  # pragma: no cover - psutil rarely fails
        return {"cpu": None, "ram": None}


def _normalize_lang_code(lang: str) -> str:
    normalized_lang = (lang or "").strip().lower()
    if not normalized_lang:
        raise ValueError("Leerer Sprachcode")
    return normalized_lang


def _resolve_hf_model_name(lang: str) -> str | None:
    hf_code = iso1_to_iso3_hf.get(lang)
    if hf_code is None:
        return None
    return f"facebook/mms-tts-{hf_code}"


def resolve_tts_model_name(lang: str) -> str:
    normalized_lang = _normalize_lang_code(lang)
    if normalized_lang in tts_models:
        return tts_models[normalized_lang]

    hf_model_name = _resolve_hf_model_name(normalized_lang)
    if hf_model_name:
        return hf_model_name

    raise ValueError(f"Keine TTS-Stimme für Sprache '{normalized_lang}' konfiguriert.")


def _load_coqui_model(normalized_lang: str):
    model_name = tts_models[normalized_lang]
    print(f"Lade TTS-Modell für Sprache: {normalized_lang} ({model_name})")
    tts_device = "cuda" if torch.cuda.is_available() else "cpu"
    model = TTSApi(model_name=model_name).to(tts_device)
    setattr(model, "_device", tts_device)
    try:
        print(f"Modell-Device: {next(model.parameters()).device}")
    except Exception as exc:
        print(f"Device-Check nicht möglich: {exc}")
    print(
        f"TTS-Modell für Sprache {normalized_lang} erfolgreich geladen auf {tts_device}."
    )
    return model


def _load_hf_tts_model(normalized_lang: str):
    hf_model_id = _resolve_hf_model_name(normalized_lang)
    if hf_model_id is None:
        return None

    print(
        f"Versuche HuggingFace MMS-TTS für Sprache: {normalized_lang} ({hf_model_id})"
    )
    tts_pipe = pipeline("text-to-speech", model=hf_model_id)
    print(f"HuggingFace MMS-TTS für Sprache {normalized_lang} erfolgreich geladen.")
    return tts_pipe


def get_tts_model(lang: str):
    normalized_lang = _normalize_lang_code(lang)
    if normalized_lang in tts_model_cache:
        return tts_model_cache[normalized_lang]

    if normalized_lang in tts_models and TTSApi:
        try:
            model = _load_coqui_model(normalized_lang)
            tts_model_cache[normalized_lang] = model
            return model
        except Exception as exc:
            print(f"Coqui-TTS fehlgeschlagen: {exc}")

    try:
        tts_pipe = _load_hf_tts_model(normalized_lang)
        if tts_pipe is None:
            return None
        tts_model_cache[normalized_lang] = tts_pipe
        return tts_pipe
    except Exception as exc:
        print(
            f"Fehler beim Laden von HuggingFace MMS-TTS für Sprache {normalized_lang}: {exc}"
        )
        print(traceback.format_exc())
        return None


def _seed_for_request(
    session_id: str | None, text: str, debug_info: Dict[str, Any]
) -> int:
    if session_id:
        debug_info["seed_source"] = "session_id"
        return hash(session_id) % (2**32)

    debug_info["seed_source"] = "text_hash"
    return hash(text) % (2**32)


def _apply_seed(seed: int) -> None:
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)


def _audio_response(
    audio_bytes: bytes,
    model_name: str,
    lang: str,
    debug_active: bool,
    debug_info: Dict[str, Any],
) -> Response:
    headers = {
        "X-TTS-Model": model_name,
        "X-TTS-Language": lang,
    }
    if debug_active:
        headers["X-Debug-Info"] = str(debug_info)
    return Response(content=audio_bytes, media_type=AUDIO_WAV_MIME, headers=headers)


def _error_response(
    debug_active: bool,
    debug_info: Dict[str, Any],
    status_code: int,
    *,
    fallback: bool,
    error: str,
) -> JSONResponse:
    if debug_active:
        return JSONResponse(
            content={"fallback": fallback, "error": error, "debug": debug_info},
            status_code=status_code,
        )

    return JSONResponse(
        content={"fallback": fallback, "error": error},
        status_code=status_code,
    )


def _collect_gpu_metrics() -> Dict[str, Any]:
    """Return GPU availability and utilization details for TTS service."""
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


def _append_gpu_signal(
    reasons: List[str], gpu_device: Dict[str, Any], threshold_gpu: int
) -> None:
    gpu_util = gpu_device.get("utilization_percent")
    mem_util = gpu_device.get("memory_utilization")
    if gpu_util is not None and gpu_util >= threshold_gpu:
        reasons.append(f"gpu{gpu_device.get('index')}_util>={threshold_gpu}")
    if mem_util is not None and mem_util >= threshold_gpu:
        reasons.append(f"gpu{gpu_device.get('index')}_mem>={threshold_gpu}")


def _derive_auto_scaling_signal(metrics: Dict[str, Any]) -> Dict[str, Any]:
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
    for gpu_device in gpu_info.get("devices", []):
        _append_gpu_signal(reasons, gpu_device, threshold_gpu)

    recommended_action = "scale_up" if reasons else "steady"
    return {"recommended_action": recommended_action, "reasons": reasons}


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


def _resolve_synthesis_request(
    data: Dict[str, Any], debug_info: Dict[str, Any], start: float
) -> tuple[str, str, str | None, str]:
    text = data.get("tts_text") or data.get("text", "Hallo Welt")
    lang = data.get("lang", "de")
    session_id = data.get("session_id")

    if not isinstance(text, str) or not text.strip():
        debug_info["error"] = "Field 'text' must be a non-empty string"
        _update_duration(debug_info, start)
        raise ValueError(debug_info["error"])

    normalized_lang = _normalize_lang_code(lang)
    model_name = resolve_tts_model_name(normalized_lang)
    return text, normalized_lang, session_id, model_name


def _extract_audio_payload(result: Any) -> tuple[Any, int]:
    if isinstance(result, dict):
        return result["audio"], result.get("sampling_rate", 16000)
    return result[0]["audio"], 16000


def _synthesize_hf_audio(tts_model: Any, text: str) -> bytes:
    import numpy as np

    result = tts_model(text)
    audio, sampling_rate = _extract_audio_payload(result)
    print(
        "MMS-TTS Output: type=%s, shape=%s, size=%s, sampling_rate=%s"
        % (
            type(audio),
            getattr(audio, "shape", None),
            getattr(audio, "size", None),
            sampling_rate,
        )
    )
    if isinstance(audio, np.ndarray):
        audio = audio.squeeze().astype(np.float32)
        if audio.size == 0:
            print("Warnung: MMS-TTS Output ist leer!")
    else:
        print(f"Warnung: MMS-TTS Output ist kein numpy-Array, sondern: {type(audio)}")
    return _numpy_audio_to_wav_bytes(audio, sampling_rate)


async def _render_audio_bytes(tts_model: Any, text: str) -> tuple[bytes, bool]:
    if hasattr(tts_model, "tts_to_file"):
        audio_bytes = await asyncio.to_thread(
            _coqui_tts_to_audio_bytes, tts_model, text
        )
        return audio_bytes, False
    if hasattr(tts_model, "__call__"):
        audio_bytes = await asyncio.to_thread(_synthesize_hf_audio, tts_model, text)
        return audio_bytes, True
    raise RuntimeError("Unbekannter TTS-Modelltyp")


@app.get("/health")
def health():
    configured_langs = sorted(tts_models.keys())
    model_available = any(tts_model_cache.values())
    resources = _collect_resource_metrics()
    autoscaling = _derive_auto_scaling_signal(resources)
    gpu_info = resources.get("gpu", {})
    gpu_available = gpu_info.get("available", False)
    gpu_used = False
    gpu_errors: List[str] = (
        list(gpu_info.get("errors", [])) if gpu_info.get("errors") else []
    )

    loaded_models = {}
    for lang in configured_langs:
        loaded_models[lang] = (
            lang in tts_model_cache and tts_model_cache[lang] is not None
        )

    for loaded_model in tts_model_cache.values():
        try:
            if hasattr(loaded_model, "_device"):
                if loaded_model._device == "cuda":
                    gpu_used = True
            elif hasattr(loaded_model, "device") and str(
                loaded_model.device
            ).startswith("cuda"):
                gpu_used = True
            else:
                gpu_errors.append("model_missing_device_attribute")
        except Exception as exc:
            gpu_errors.append(str(exc))

    if not gpu_available and not gpu_errors:
        gpu_errors.append("torch.cuda.is_available()==False")

    health_status.set(1 if model_available else 0)
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available,
        "gpu_used": gpu_used,
        "gpu_error": "; ".join(gpu_errors) if gpu_errors else None,
        "configured_models": {"coqui": tts_models},
        "loaded_models": loaded_models,
        "resources": resources,
        "autoscaling": autoscaling,
    }


@app.get("/supported-languages")
def supported_languages():
    all_langs = set(tts_models) | set(iso1_to_iso3_hf)
    return {"languages": sorted(all_langs)}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")


@app.post("/synthesize", responses=SYNTHESIS_ERROR_RESPONSES)
async def synthesize(request: Request):
    start = time.perf_counter()
    data = await request.json()
    text = data.get("tts_text") or data.get("text", "Hallo Welt")
    lang = data.get("lang", "de")
    debug_active = (
        str(data.get("debug", "false")).lower() == "true"
        or str(request.query_params.get("debug", "false")).lower() == "true"
    )
    debug_info = _build_debug_info(text, lang)

    if not isinstance(text, str) or not text.strip():
        debug_info["error"] = "Field 'text' must be a non-empty string"
        _update_duration(debug_info, start)
        return _error_response(
            debug_active,
            debug_info,
            400,
            fallback=False,
            error=debug_info["error"],
        )

    try:
        text, normalized_lang, session_id, model_name = _resolve_synthesis_request(
            data, debug_info, start
        )
    except ValueError as exc:
        debug_info["error"] = str(exc)
        _update_duration(debug_info, start)
        return _error_response(
            debug_active,
            debug_info,
            400,
            fallback=False,
            error=debug_info["error"],
        )

    tts_model = get_tts_model(normalized_lang)
    debug_info["model"] = model_name
    if not tts_model:
        debug_info["error"] = (
            f"Kein TTS-Modell für Sprache '{normalized_lang}' (Konfig oder Download prüfen)."
        )
        _update_duration(debug_info, start)
        return _error_response(
            debug_active,
            debug_info,
            503,
            fallback=True,
            error=debug_info["error"],
        )

    try:
        seed = _seed_for_request(session_id, text, debug_info)
        _apply_seed(seed)
        audio_bytes, used_fallback = await _render_audio_bytes(tts_model, text)
        debug_info["output"] = AUDIO_WAV_MIME
        _update_duration(debug_info, start)
        response_model_name = (
            f"{model_name} (MMS-TTS Fallback)" if used_fallback else model_name
        )
        return _audio_response(
            audio_bytes,
            response_model_name,
            normalized_lang,
            debug_active,
            debug_info,
        )
    except Exception as exc:
        debug_info["error"] = str(exc)
        debug_info["traceback"] = traceback.format_exc()
        _update_duration(debug_info, start)
        return _error_response(
            debug_active,
            debug_info,
            500,
            fallback=False,
            error=f"TTS fehlgeschlagen: {exc}",
        )
