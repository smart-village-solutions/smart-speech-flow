# Stelle sicher, dass die Funktion get_tts_model vorhanden ist
def get_tts_model(lang: str):
    if lang in tts_model_cache:
        return tts_model_cache[lang]

    # Erst Coqui-TTS versuchen
    if TTSApi:
        try:
            model_name = resolve_tts_model_name(lang)
            print(f"Lade TTS-Modell für Sprache: {lang} ({model_name})")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = TTSApi(model_name=model_name).to(device)
            setattr(model, "_device", device)
            # Debug: Zeige das tatsächliche Device des Modells
            try:
                print(f"Modell-Device: {next(model.parameters()).device}")
            except Exception as e:
                print(f"Device-Check nicht möglich: {e}")
            tts_model_cache[lang] = model
            print(f"TTS-Modell für Sprache {lang} erfolgreich geladen auf {device}.")
            return model
        except Exception as e:
            print(f"Coqui-TTS fehlgeschlagen: {e}")
            # Fallback: HuggingFace MMS-TTS
    # Mapping ISO-639-1 → ISO-639-3 für HuggingFace MMS-TTS
    iso1_to_iso3_hf = {
        "de": "deu",
        "en": "eng",
        "ar": "ara",
        "tr": "tur",
        "ru": "rus",
        "uk": "ukr",
        "am": "amh",
        "ti": "tir",
        "ku": "kmr",  # Kurmancî
        "fa": "fas",  # Persian
    }
    try:
        hf_code = iso1_to_iso3_hf.get(lang, lang)
        hf_model_id = f"facebook/mms-tts-{hf_code}"
        print(f"Versuche HuggingFace MMS-TTS für Sprache: {lang} ({hf_model_id})")
        tts_pipe = pipeline("text-to-speech", model=hf_model_id)
        tts_model_cache[lang] = tts_pipe
        print(f"HuggingFace MMS-TTS für Sprache {lang} erfolgreich geladen.")
        return tts_pipe
    except Exception as e:
        print(f"Fehler beim Laden von HuggingFace MMS-TTS für Sprache {lang}: {e}")
        import traceback

        print(traceback.format_exc())
        return None


from typing import Any, Dict, List

import soundfile as sf
import torch
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, generate_latest
from transformers import pipeline

device = "cuda" if torch.cuda.is_available() else "cpu"
try:
    from TTS.api import TTS

    TTSApi = TTS
except ImportError:
    TTSApi = None
import tempfile

try:
    import psutil
except ImportError:  # pragma: no cover - provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

_nvml_initialized = False


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
    for device in gpu_info.get("devices", []):
        gpu_util = device.get("utilization_percent")
        mem_util = device.get("memory_utilization")
        if gpu_util is not None and gpu_util >= threshold_gpu:
            reasons.append(f"gpu{device.get('index')}_util>={threshold_gpu}")
        if mem_util is not None and mem_util >= threshold_gpu:
            reasons.append(f"gpu{device.get('index')}_mem>={threshold_gpu}")

    recommended_action = "scale_up" if reasons else "steady"
    return {"recommended_action": recommended_action, "reasons": reasons}


app = FastAPI(title="TTS Service")
requests_total = Counter("tts_requests_total", "Total TTS requests")
health_status = Gauge("tts_health_status", "Health status of TTS service")
MODEL_PATH = "/models/tts_model.pt"

# Primäre, konkret verifizierte Coqui-Modelle aus deiner Liste/Umgebung
tts_models = {
    "de": "tts_models/de/thorsten/vits",  # Deutsch, verfügbar
    "en": "tts_models/en/ljspeech/vits",  # Englisch, verfügbar
    "tr": "tts_models/tr/common-voice/glow-tts",  # Türkisch, verfügbar
    "fa": "tts_models/fa/custom/glow-tts",  # Persisch, verfügbar (Custom)
    "uk": "tts_models/uk/mai/vits",  # Ukrainisch, verfügbar
}


tts_model_cache = {}


def resolve_tts_model_name(lang: str) -> str:
    """
    1) Versuche zuerst ein verifiziertes Coqui-Modell (tts_models[...] aus deiner Liste).
    2) Sonst Fehler.
    """
    lang = (lang or "").strip().lower()
    if not lang:
        raise ValueError("Leerer Sprachcode")
    if lang in tts_models:
        return tts_models[lang]
    raise ValueError(f"Keine TTS-Stimme für Sprache '{lang}' konfiguriert.")

    if lang in tts_model_cache:
        return tts_model_cache[lang]

    # Erst Coqui-TTS versuchen
    if TTSApi:
        try:
            model_name = resolve_tts_model_name(lang)
            print(f"Lade TTS-Modell für Sprache: {lang} ({model_name})")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = TTSApi(model_name=model_name).to(device)
            setattr(model, "_device", device)
            tts_model_cache[lang] = model
            print(f"TTS-Modell für Sprache {lang} erfolgreich geladen auf {device}.")
            return model
        except Exception as e:
            print(f"Coqui-TTS fehlgeschlagen: {e}")
            # Fallback: HuggingFace MMS-TTS
    try:
        hf_model_id = f"facebook/mms-tts-{lang}"
        print(f"Versuche HuggingFace MMS-TTS für Sprache: {lang} ({hf_model_id})")
        tts_pipe = pipeline("text-to-speech", model=hf_model_id)
        tts_model_cache[lang] = tts_pipe
        print(f"HuggingFace MMS-TTS für Sprache {lang} erfolgreich geladen.")
        return tts_pipe
    except Exception as e:
        print(f"Fehler beim Laden von HuggingFace MMS-TTS für Sprache {lang}: {e}")
        import traceback

        print(traceback.format_exc())
        return None


@app.get("/health")
def health():
    # Verfügbare Sprachen aus Konfig (nur Coqui)
    configured_langs = sorted(list(tts_models.keys()))
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
        loaded = lang in tts_model_cache and tts_model_cache[lang] is not None
        loaded_models[lang] = loaded

    for model in tts_model_cache.values():
        try:
            if hasattr(model, "_device"):
                if model._device == "cuda":
                    gpu_used = True
            elif hasattr(model, "device") and str(model.device).startswith("cuda"):
                gpu_used = True
            else:
                gpu_errors.append("model_missing_device_attribute")
        except Exception as e:
            gpu_errors.append(str(e))

    if not gpu_available and not gpu_errors:
        gpu_errors.append("torch.cuda.is_available()==False")

    gpu_error = "; ".join(gpu_errors) if gpu_errors else None

    health_status.set(1 if model_available else 0)
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available,
        "gpu_used": gpu_used,
        "gpu_error": gpu_error,
        "configured_models": {"coqui": tts_models},
        "loaded_models": loaded_models,
        "resources": resources,
        "autoscaling": autoscaling,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")


@app.post("/synthesize")
async def synthesize(request: Request):
    import time
    import traceback

    start = time.perf_counter()
    data = await request.json()
    text = data.get("tts_text") or data.get("text", "Hallo Welt")
    lang = data.get("lang", "de")
    session_id = data.get("session_id")  # Optional: für session-basierten Seed
    debug_active = (
        str(data.get("debug", "false")).lower() == "true"
        or str(request.query_params.get("debug", "false")).lower() == "true"
    )
    system_stats = {"cpu": None, "ram": None}
    if psutil is not None:
        try:
            system_stats = {
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
            }
        except Exception:  # pragma: no cover - psutil rarely fails
            system_stats = {"cpu": None, "ram": None}
    debug_info = {
        "input": {"text": text, "lang": lang},
        "output": None,
        "error": None,
        "duration": None,
        "model": None,
        "system": system_stats,
    }

    # Minimalvalidierung
    if not isinstance(text, str) or not text.strip():
        debug_info["error"] = "Field 'text' must be a non-empty string"
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        if debug_active:
            return JSONResponse(
                content={
                    "fallback": False,
                    "error": debug_info["error"],
                    "debug": debug_info,
                },
                status_code=400,
            )
        return JSONResponse(
            content={"error": "Field 'text' must be a non-empty string"},
            status_code=400,
        )

    tts_model = get_tts_model(lang)
    model_name = resolve_tts_model_name(lang)  # Hole den Modellnamen für Metadaten
    debug_info["model"] = model_name
    if not tts_model:
        debug_info["error"] = (
            f"Kein TTS-Modell für Sprache '{lang}' (Konfig oder Download prüfen)."
        )
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        if debug_active:
            return JSONResponse(
                content={
                    "fallback": True,
                    "error": debug_info["error"],
                    "debug": debug_info,
                },
                status_code=503,
            )
        return JSONResponse(
            content={"fallback": True, "error": debug_info["error"]},
            status_code=503,
        )

    try:
        # Coqui-TTS-Modell
        if hasattr(tts_model, "tts_to_file"):
            # Setze deterministischen Seed basierend auf session_id (falls vorhanden)
            # oder Text-Hash (Fallback). Dies sorgt für konsistente Stimm-Charakteristik
            # innerhalb einer Session
            if session_id:
                seed = hash(session_id) % (2**32)
                debug_info["seed_source"] = "session_id"
                print(f"🎲 TTS Seed: {seed} (von session_id: {session_id})")
            else:
                seed = hash(text) % (2**32)
                debug_info["seed_source"] = "text_hash"
                print(f"🎲 TTS Seed: {seed} (von text_hash)")

            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed(seed)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tts_model.tts_to_file(text=text, file_path=tmp.name)
                tmp_path = tmp.name

            # Lese Audio-Datei und sende als Response mit Custom-Headern
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()

            debug_info["output"] = "audio/wav"
            debug_info["duration"] = round(time.perf_counter() - start, 3)

            headers = {
                "X-TTS-Model": model_name,
                "X-TTS-Language": lang,
            }
            if debug_active:
                headers["X-Debug-Info"] = str(debug_info)

            return Response(
                content=audio_bytes, media_type="audio/wav", headers=headers
            )
        # HuggingFace MMS-TTS pipeline
        elif hasattr(tts_model, "__call__"):
            import numpy as np

            # Setze deterministischen Seed auch für MMS-TTS
            if session_id:
                seed = hash(session_id) % (2**32)
                debug_info["seed_source"] = "session_id"
                print(f"🎲 MMS-TTS Seed: {seed} (von session_id: {session_id})")
            else:
                seed = hash(text) % (2**32)
                debug_info["seed_source"] = "text_hash"
                print(f"🎲 MMS-TTS Seed: {seed} (von text_hash)")

            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed(seed)

            tts_pipe = tts_model
            result = tts_pipe(text)
            audio = result["audio"] if isinstance(result, dict) else result[0]["audio"]
            sampling_rate = result.get("sampling_rate", 16000)
            print(
                f"MMS-TTS Output: type={type(audio)}, shape={getattr(audio, 'shape', None)}, size={getattr(audio, 'size', None)}, sampling_rate={sampling_rate}"
            )
            if isinstance(audio, np.ndarray):
                audio = audio.squeeze()
                audio = audio.astype(np.float32)
            if not isinstance(audio, np.ndarray):
                print(
                    f"Warnung: MMS-TTS Output ist kein numpy-Array, sondern: {type(audio)}"
                )
            if isinstance(audio, np.ndarray) and audio.size == 0:
                print("Warnung: MMS-TTS Output ist leer!")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio, sampling_rate)
                tmp_path = tmp.name

            # Lese Audio-Datei und sende als Response mit Custom-Headern
            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()

            debug_info["output"] = "audio/wav"
            debug_info["duration"] = round(time.perf_counter() - start, 3)

            headers = {
                "X-TTS-Model": model_name + " (MMS-TTS Fallback)",
                "X-TTS-Language": lang,
            }
            if debug_active:
                headers["X-Debug-Info"] = str(debug_info)

            return Response(
                content=audio_bytes, media_type="audio/wav", headers=headers
            )
        else:
            raise RuntimeError("Unbekannter TTS-Modelltyp")
    except Exception as e:
        debug_info["error"] = str(e)
        debug_info["traceback"] = traceback.format_exc()
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        if debug_active:
            return JSONResponse(
                content={
                    "fallback": False,
                    "error": f"TTS fehlgeschlagen: {str(e)}",
                    "debug": debug_info,
                },
                status_code=500,
            )
        return JSONResponse(
            content={"fallback": False, "error": f"TTS fehlgeschlagen: {str(e)}"},
            status_code=500,
        )
