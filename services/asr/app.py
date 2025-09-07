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
    cmd = [ffmpeg_bin, "-y", "-i", in_path, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16"]
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
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import Response
from prometheus_client import Counter, Gauge, generate_latest
import os
import torch
import tempfile
import shutil
try:
    import whisper
except ImportError:
    whisper = None

app = FastAPI(title="ASR Service")
SUPPORTED_LANGS = ["de", "en", "ar", "tr", "am", "fa", "ru", "uk"]
requests_total = Counter('asr_requests_total', 'Total ASR requests')
health_status = Gauge('asr_health_status', 'Health status of ASR service')
model = None
model_loaded = False
if whisper:
    try:
        model = whisper.load_model("base", device="cuda" if torch.cuda.is_available() else "cpu")
        model_loaded = True
    except Exception as e:
        model = None
        model_loaded = False

@app.get("/health")
def health():
    model_available = model_loaded
    gpu_available = torch.cuda.is_available() if torch else False
    health_status.set(1 if model_available else 0)
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available
    }

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), lang: str = Form("de")):
    requests_total.inc()
    if lang not in SUPPORTED_LANGS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Unsupported language code: {lang}")
    if not model_loaded:
        return {"text": "Hallo Welt", "fallback": True}
    # Speichere die Audiodatei temporär
    with tempfile.NamedTemporaryFile(delete=False, suffix=".input") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    norm_path = None
    try:
        # Normalisiere das Audio
        norm_path = normalize_to_wav16k(tmp_path)
        # Sprache an Whisper übergeben
        result = model.transcribe(norm_path, language=lang)
        text = result.get("text", "")
    except Exception as e:
        text = "Fehler bei der Transkription"
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if norm_path and os.path.exists(norm_path):
            os.remove(norm_path)
    return {"text": text, "fallback": False}
