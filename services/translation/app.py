import os
import re
import threading
import time
from typing import Any, Dict, List

import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from prometheus_client import Counter, Gauge, Histogram, generate_latest

from services.gpu_metrics import collect_gpu_metrics

try:
    import psutil
except ImportError:  # pragma: no cover - dependency provided via requirements
    psutil = None

try:
    import pynvml
except ImportError:  # pragma: no cover - optional dependency
    pynvml = None

_nvml_initialized = False
TRANSLATION_ERROR_RESPONSES = {
    400: {"description": "Invalid translation request"},
    500: {"description": "Translation failed"},
    503: {"description": "Translation model unavailable"},
}


def _get_system_stats() -> Dict[str, Any]:
    if psutil is None:
        return {"cpu": None, "ram": None}

    try:
        return {
            "cpu": psutil.cpu_percent(),
            "ram": psutil.virtual_memory().percent,
        }
    except Exception:  # pragma: no cover - psutil rarely fails at runtime
        return {"cpu": None, "ram": None}


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
        outputs = _translate_texts(texts, source_lang, target_lang, gen_overrides)
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
