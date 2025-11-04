import os
import re
import threading
import time
from typing import Any, Dict, List, Union

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest

try:
    import psutil
except ImportError:  # pragma: no cover - dependency provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

_nvml_initialized = False


def _collect_gpu_metrics() -> Dict[str, Any]:
    """Return GPU availability and utilization details if devices are present."""
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
# App & Metrics
# ----------------------------
app = FastAPI(title="Translation Service (M2M100)")
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
        supported_langs = sorted(list(m2m_tokenizer.lang_code_to_id.keys()))
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


def _as_list(text: Union[str, List[str]]) -> List[str]:
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
    gen_kwargs = dict(
        forced_bos_token_id=forced_bos_id,
        max_new_tokens=GEN_MAX_NEW_TOKENS,
        num_beams=GEN_NUM_BEAMS,
        length_penalty=GEN_LENGTH_PENALTY,
        early_stopping=GEN_EARLY_STOPPING,
    )
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


@app.get("/languages")
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


@app.post("/translate")
async def translate(request: Request):
    debug_active = False
    system_stats = {"cpu": None, "ram": None}
    if psutil is not None:
        try:
            system_stats = {
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
            }
        except Exception:  # pragma: no cover - psutil rarely fails at runtime
            system_stats = {"cpu": None, "ram": None}
    debug_info = {
        "input": None,
        "output": None,
        "error": None,
        "duration": None,
        "model": MODEL_NAME,
        "system": system_stats,
    }
    try:
        payload = await request.json()
        debug_active = (
            str(payload.get("debug", "false")).lower() == "true"
            or str(request.query_params.get("debug", "false")).lower() == "true"
        )
    except Exception:
        errors_total.inc()
        debug_info["error"] = "Invalid JSON payload"
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=400
            )
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    text_in = payload.get("text")
    source_lang = payload.get("source_lang")
    target_lang = payload.get("target_lang")
    gen_overrides = payload.get("generation", {})
    debug_info["input"] = {
        "text": text_in,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "generation": gen_overrides,
    }

    if not model_loaded or m2m_model is None or m2m_tokenizer is None:
        debug_info["error"] = "Model unavailable"
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=503
            )
        raise HTTPException(status_code=503, detail="Model unavailable")

    if text_in is None or (
        DENY_EMPTY and (isinstance(text_in, str) and not text_in.strip())
    ):
        errors_total.inc()
        debug_info["error"] = (
            "Field 'text' must be a non-empty string or list of strings"
        )
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=400
            )
        raise HTTPException(
            status_code=400,
            detail="Field 'text' must be a non-empty string or list of strings",
        )

    if not source_lang or not target_lang:
        errors_total.inc()
        debug_info["error"] = "Fields 'source_lang' and 'target_lang' are required"
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=400
            )
        raise HTTPException(
            status_code=400,
            detail="Fields 'source_lang' and 'target_lang' are required",
        )

    try:
        _validate_lang(source_lang)
        _validate_lang(target_lang)
    except Exception as e:
        debug_info["error"] = str(e)
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=400
            )
        raise

    texts: List[str] = _as_list(text_in)
    start = time.perf_counter()
    outputs: List[str] = []

    try:
        for t in texts:
            if not isinstance(t, str):
                t = str(t)

            if len(t) > MAX_INPUT_CHARS:
                chunks = _chunk_text_if_needed(t)
                partials = []
                for ch in chunks:
                    partials.append(
                        _generate_single(ch, source_lang, target_lang, gen_overrides)
                    )
                outputs.append(" ".join(partials))
            else:
                outputs.append(
                    _generate_single(t, source_lang, target_lang, gen_overrides)
                )

        elapsed = time.perf_counter() - start
        debug_info["output"] = outputs if isinstance(text_in, list) else outputs[0]
        debug_info["duration"] = round(elapsed, 3)
        debug_info["error"] = None
        # Latenz an Prometheus melden
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
            "translations": outputs if isinstance(text_in, list) else outputs[0],
        }
        # Romanisierte Variante für TTS ergänzen
        try:
            from uroman import uromanize

            if isinstance(outputs, list):
                tts_text = [uromanize(o) for o in outputs]
            else:
                tts_text = uromanize(outputs)
            response["tts_text"] = tts_text
        except ImportError:
            response["tts_text"] = None
        if debug_active:
            response["debug"] = debug_info
        return JSONResponse(response)
    except HTTPException as e:
        debug_info["error"] = str(e)
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=400
            )
        raise
    except Exception as e:
        errors_total.inc()
        debug_info["error"] = f"Translation failed: {e}"
        debug_info["duration"] = round(time.perf_counter() - start, 3)
        if debug_active:
            return JSONResponse(
                {"translations": None, "debug": debug_info}, status_code=500
            )
        raise HTTPException(status_code=500, detail=f"Translation failed: {e}")
