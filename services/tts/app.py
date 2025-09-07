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
from transformers import pipeline
import soundfile as sf
from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse, JSONResponse
import re
from prometheus_client import Counter, Gauge, generate_latest
import os
import torch
device = "cuda" if torch.cuda.is_available() else "cpu"
try:
    from TTS.api import TTS as TTSApi
except ImportError:
    TTSApi = None
import tempfile
import base64

app = FastAPI(title="TTS Service")
requests_total = Counter('tts_requests_total', 'Total TTS requests')
health_status = Gauge('tts_health_status', 'Health status of TTS service')
MODEL_PATH = "/models/tts_model.pt"

# Primäre, konkret verifizierte Coqui-Modelle aus deiner Liste/Umgebung
tts_models = {
    "de": "tts_models/de/thorsten/vits",           # Deutsch, verfügbar
    "en": "tts_models/en/ljspeech/vits",           # Englisch, verfügbar
    "tr": "tts_models/tr/common-voice/glow-tts",   # Türkisch, verfügbar
    "fa": "tts_models/fa/custom/glow-tts",         # Persisch, verfügbar (Custom)
    "uk": "tts_models/uk/mai/vits"                 # Ukrainisch, verfügbar
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
    gpu_available = torch.cuda.is_available() if torch else False
    gpu_used = False
    gpu_error = None

    loaded_models = {}
    for lang in configured_langs:
        loaded = lang in tts_model_cache and tts_model_cache[lang] is not None
        loaded_models[lang] = loaded

    for model in tts_model_cache.values():
        try:
            if hasattr(model, "_device"):
                if model._device == "cuda":
                    gpu_used = True
            else:
                gpu_error = "_device not found"
        except Exception as e:
            gpu_error = str(e)

    if not gpu_available and not gpu_error:
        gpu_error = "torch.cuda.is_available() == False"

    health_status.set(1 if model_available else 0)
    return {
        "status": "ok" if model_available else "degraded",
        "model": model_available,
        "gpu": gpu_available,
        "gpu_used": gpu_used,
        "gpu_error": gpu_error,
        "configured_models": {
            "coqui": tts_models
        },
        "loaded_models": loaded_models
    }

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

@app.post("/synthesize")
async def synthesize(request: Request):
    requests_total.inc()
    data = await request.json()
    text = data.get("text", "Hallo Welt")
    lang = data.get("lang", "de")

    # Minimalvalidierung
    if not isinstance(text, str) or not text.strip():
        return JSONResponse(
            content={"error": "Field 'text' must be a non-empty string"}, status_code=400
        )

    tts_model = get_tts_model(lang)
    if not tts_model:
        return JSONResponse(
            content={"fallback": True, "error": f"Kein TTS-Modell für Sprache '{lang}' (Konfig oder Download prüfen)."},
            status_code=503
        )

    import traceback
    debug_info = {}
    try:
        debug_info["model_loaded"] = tts_model is not None
        debug_info["lang"] = lang
        debug_info["text_len"] = len(text)
        # Coqui-TTS-Modell
        if hasattr(tts_model, "tts_to_file"):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                debug_info["tmp_path"] = tmp.name
                tts_model.tts_to_file(text=text, file_path=tmp.name)
                tmp_path = tmp.name
            return FileResponse(tmp_path, media_type="audio/wav", filename="output.wav")
        # HuggingFace MMS-TTS pipeline
        elif hasattr(tts_model, "__call__"):
            tts_pipe = tts_model
            result = tts_pipe(text)
            # Das Ergebnis enthält ein 'audio' Feld mit einem numpy-Array
            audio = result["audio"] if isinstance(result, dict) else result[0]["audio"]
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio, 16000)
                debug_info["tmp_path"] = tmp.name
                tmp_path = tmp.name
            return FileResponse(tmp_path, media_type="audio/wav", filename="output.wav")
        else:
            raise RuntimeError("Unbekannter TTS-Modelltyp")
    except Exception as e:
        debug_info["error"] = str(e)
        debug_info["traceback"] = traceback.format_exc()
        return JSONResponse(
            content={"fallback": False, "error": f"TTS fehlgeschlagen: {str(e)}", "debug": debug_info},
            status_code=500
        )
