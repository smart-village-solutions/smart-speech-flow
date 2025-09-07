import os
import time
import threading
import re
from typing import List, Union, Dict, Any

import torch
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response, JSONResponse
from prometheus_client import Counter, Gauge, Histogram, generate_latest

try:
    from transformers import M2M100ForConditionalGeneration, M2M100Tokenizer
except ImportError:
    M2M100ForConditionalGeneration = None
    M2M100Tokenizer = None

# ----------------------------
# Config
# ----------------------------
MODEL_NAME = os.getenv("MODEL_NAME", "facebook/m2m100_1.2B")  # oder "facebook/m2m100_418M"
PREFER_FP16 = os.getenv("PREFER_FP16", "1") == "1"            # FP16 nur auf GPU
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
tokens_generated_total = Counter("translation_tokens_generated_total", "Total tokens generated")
health_status = Gauge("translation_health_status", "Health status of Translation service")  # 1 ok, 0 degraded
request_latency = Histogram(
    "translation_request_latency_seconds",
    "Latency of translation requests",
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 4, 8, 16, 32)
)

# ----------------------------
# Model Loading
# ----------------------------
m2m_model = None
m2m_tokenizer = None
tokenizer_lock = threading.Lock()
device = torch.device(DEVICE_STR if torch.cuda.is_available() or DEVICE_STR.startswith("cpu") else "cpu")
dtype = torch.float16 if (device.type == "cuda" and PREFER_FP16) else torch.float32

model_loaded = False
load_error = None
supported_langs: List[str] = []

if M2M100ForConditionalGeneration and M2M100Tokenizer:
    try:
        print(f"Loading model: {MODEL_NAME} on {device} (dtype={dtype})")
        m2m_tokenizer = M2M100Tokenizer.from_pretrained(MODEL_NAME)
        m2m_model = M2M100ForConditionalGeneration.from_pretrained(MODEL_NAME, torch_dtype=dtype)
        m2m_model.to(device)
        m2m_model.eval()
        model_loaded = True
        supported_langs = sorted(list(m2m_tokenizer.lang_code_to_id.keys()))
        print(f"Loaded. Supported langs ({len(supported_langs)}): {', '.join(supported_langs[:10])} ...")
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
            detail=f"Unsupported language code '{code}'. Use one of: {', '.join(supported_langs)}"
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

def _generate_single(text: str, source_lang: str, target_lang: str, gen_overrides: Dict[str, Any]) -> str:
    # Nebenläufigkeit: src_lang ist mutable → Lock
    with tokenizer_lock:
        m2m_tokenizer.src_lang = source_lang
        encoded = m2m_tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=MAX_INPUT_TOKENS
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
        early_stopping=GEN_EARLY_STOPPING
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
    health_status.set(1 if ok else 0)
    return {
        "status": "ok" if ok else "degraded",
        "model_loaded": ok,
        "model_name": MODEL_NAME,
        "device": str(device),
        "dtype": "fp16" if dtype == torch.float16 else "fp32",
        "gpu": torch.cuda.is_available(),
        "error": load_error,
        "supported_languages": len(supported_langs)
    }

@app.get("/languages")
def languages():
    if not model_loaded:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return {"languages": supported_langs, "count": len(supported_langs), "model": MODEL_NAME}

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8")

@app.post("/translate")
async def translate(request: Request):
    if not model_loaded or m2m_model is None or m2m_tokenizer is None:
        raise HTTPException(status_code=503, detail="Model unavailable")

    requests_total.inc()

    try:
        payload = await request.json()
    except Exception:
        errors_total.inc()
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    text_in = payload.get("text")
    source_lang = payload.get("source_lang")
    target_lang = payload.get("target_lang")
    gen_overrides = payload.get("generation", {})

    if text_in is None or (DENY_EMPTY and (isinstance(text_in, str) and not text_in.strip())):
        errors_total.inc()
        raise HTTPException(status_code=400, detail="Field 'text' must be a non-empty string or list of strings")

    if not source_lang or not target_lang:
        errors_total.inc()
        raise HTTPException(status_code=400, detail="Fields 'source_lang' and 'target_lang' are required")

    _validate_lang(source_lang)
    _validate_lang(target_lang)

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
                    partials.append(_generate_single(ch, source_lang, target_lang, gen_overrides))
                outputs.append(" ".join(partials))
            else:
                outputs.append(_generate_single(t, source_lang, target_lang, gen_overrides))

        elapsed = time.perf_counter() - start
        # Latenz an Prometheus melden
        try:
            request_latency.observe(elapsed)
        except Exception:
            pass
        return JSONResponse({
            "model": MODEL_NAME,
            "device": str(device),
            "dtype": "fp16" if dtype == torch.float16 else "fp32",
            "source_lang": source_lang,
            "target_lang": target_lang,
            "count": len(outputs),
            "elapsed_seconds": round(elapsed, 3),
            "translations": outputs if isinstance(text_in, list) else outputs[0]
        })
    except HTTPException:
        raise
    except Exception as e:
        errors_total.inc()
        raise HTTPException(status_code=500, detail=f"Translation failed: {e}")
