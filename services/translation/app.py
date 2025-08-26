from fastapi import FastAPI, Request
from prometheus_client import Counter, generate_latest
import os
import torch
try:
    from transformers import pipeline
except ImportError:
    pipeline = None

app = FastAPI(title="Translation Service")
requests_total = Counter('translation_requests_total', 'Total translation requests')
MODEL_PATH = "/models/translation_model.pt"
translator = None
model_loaded = False
if pipeline:
    try:
        print("Initialisiere Translation-Pipeline mit Modell: Helsinki-NLP/opus-mt-de-en")
        translator = pipeline("translation", model="Helsinki-NLP/opus-mt-de-en", device=0 if torch.cuda.is_available() else -1)
        print("Pipeline geladen:", translator)
        model_loaded = True
    except Exception as e:
        print("Fehler beim Laden des Translation-Modells:", e)
        translator = None
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

@app.post("/translate")
async def translate(request: Request):
    requests_total.inc()
    data = await request.json()
    text = data.get("text", "Hallo Welt")
    print(f"Empfangener Text aus JSON: {text}")
    if not model_loaded:
        return {"translation": "Hello World", "fallback": True}
    try:
        print(f"Übersetze Text: {text}")
        result = translator(text)
        print(f"Pipeline-Antwort: {result}")
        translation = result[0]["translation_text"]
    except Exception as e:
        print(f"Fehler bei der Übersetzung: {e}")
        translation = "Fehler bei der Übersetzung"
    return {"translation": translation, "fallback": False}
