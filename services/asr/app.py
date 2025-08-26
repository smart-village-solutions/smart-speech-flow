from fastapi import FastAPI, UploadFile, File
from prometheus_client import Counter, generate_latest
import os
import torch
import tempfile
import shutil
try:
    import whisper
except ImportError:
    whisper = None

app = FastAPI(title="ASR Service")
requests_total = Counter('asr_requests_total', 'Total ASR requests')
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
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available
    }

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; version=0.0.4'}

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    requests_total.inc()
    if not model_loaded:
        return {"text": "Hallo Welt", "fallback": True}
    # Speichere die Audiodatei temporär
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        result = model.transcribe(tmp_path)
        text = result.get("text", "")
    except Exception as e:
        text = "Fehler bei der Transkription"
    finally:
        os.remove(tmp_path)
    return {"text": text, "fallback": False}
