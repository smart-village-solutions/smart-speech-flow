from fastapi import FastAPI, UploadFile, File
import requests
from prometheus_client import Counter, generate_latest

app = FastAPI(title="API Gateway")
requests_total = Counter('gateway_requests_total', 'Total API Gateway requests')

ASR_URL = "http://asr:8000/transcribe"
TRANSLATION_URL = "http://translation:8000/translate"
TTS_URL = "http://tts:8000/synthesize"

@app.get("/health")
def health():
    # Dummy health check: alle Services erreichbar?
    return {"status": "ok"}

@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain; version=0.0.4'}

@app.post("/speech-translate")
def speech_translate(file: UploadFile = File(...)):
    requests_total.inc()
    # Dummy Orchestrierung
    asr_resp = requests.post(ASR_URL, files={"file": (file.filename, file.file, file.content_type)})
    asr_text = asr_resp.json().get("text", "")
    translation_resp = requests.post(TRANSLATION_URL, json={"text": asr_text})
    translation_text = translation_resp.json().get("translation", "")
    tts_resp = requests.post(TTS_URL, json={"text": translation_text})
    audio_bytes = tts_resp.content
    from fastapi.responses import Response
    return Response(content=audio_bytes, media_type="audio/wav")
