from fastapi import FastAPI, Request
import re
from fastapi.responses import FileResponse
from prometheus_client import Counter, generate_latest
import os
import torch
try:
    from TTS.api import TTS as TTSApi
except ImportError:
    TTSApi = None
import tempfile
import base64

app = FastAPI(title="TTS Service")
requests_total = Counter('tts_requests_total', 'Total TTS requests')
MODEL_PATH = "/models/tts_model.pt"
tts_models = {
    "de": "tts_models/de/thorsten/vits",
    "en": "tts_models/en/ljspeech/vits"
}
tts_model_cache = {}
def get_language(text):
    # Sehr einfache Spracherkennung: Wenn viele a-z und wenig Umlaute, dann englisch
    if re.search(r'[äöüß]', text, re.IGNORECASE):
        return "de"
    # Wenn viele englische Wörter, dann englisch
    if re.search(r'\b(the|and|of|to|in|is|that|it|for|on|with|as|at|by|from|was|be|are|this|have|or|an|not|but|they|his|her|she|he|you|we|us|our|your|their|them|who|what|which|when|where|why|how|can|will|would|should|could|may|might|do|does|did|has|had|were|been|being|am|i)\b', text, re.IGNORECASE):
        return "en"
    # Default: deutsch
    return "de"

def get_tts_model(lang):
    if lang in tts_model_cache:
        return tts_model_cache[lang]
    if TTSApi:
        try:
            print(f"Lade TTS-Modell für Sprache: {lang} ({tts_models[lang]})")
            tts_model_cache[lang] = TTSApi(model_name=tts_models[lang])
            print(f"TTS-Modell für Sprache {lang} erfolgreich geladen.")
            return tts_model_cache[lang]
        except Exception as e:
            print(f"Fehler beim Laden des TTS-Modells für Sprache {lang}: {e}")
            import traceback
            print(traceback.format_exc())
            return None
    print(f"TTSApi nicht verfügbar!")
    return None

@app.get("/health")
def health():
    # Prüfe, ob mindestens ein Modell geladen ist
    model_available = any(tts_model_cache.values())
    gpu_available = torch.cuda.is_available() if torch else False
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available
    }

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; version=0.0.4'}

@app.post("/synthesize")
async def synthesize(request: Request):
    requests_total.inc()
    data = await request.json()
    text = data.get("text", "Hallo Welt")
    lang = get_language(text)
    tts_model = get_tts_model(lang)
    if not tts_model:
        return {"audio": "dummy_audio_data", "fallback": True, "error": f"Kein TTS-Modell für Sprache {lang}"}
    import traceback
    debug_info = {}
    try:
        debug_info["model_loaded"] = tts_model is not None
        debug_info["tts_model_class"] = str(type(tts_model))
        debug_info["text"] = text
        debug_info["speaker_param"] = None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            debug_info["tmp_path"] = tmp.name
            tts_model.tts_to_file(text=text, file_path=tmp.name)
            tmp_path = tmp.name
        return FileResponse(tmp_path, media_type="audio/wav", filename="output.wav")
    except Exception as e:
        debug_info["model_loaded"] = False
        debug_info["error"] = str(e)
        debug_info["traceback"] = traceback.format_exc()
        return {"audio": f"Fehler bei der Synthese: {str(e)}", "fallback": False, "error": str(e), "debug": debug_info}
