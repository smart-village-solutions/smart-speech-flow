# Imports
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, Response
import requests
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from prometheus_client import Counter, generate_latest, CollectorRegistry
import base64
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="API Gateway")
# Eigene Registry, um doppelte Registrierung zu vermeiden
registry = CollectorRegistry()
requests_total = Counter('gateway_requests_total', 'Total API Gateway requests', registry=registry)

# Service-URLs für die Orchestrierung
DOCKER_ENV = os.environ.get("DOCKER_COMPOSE", "1") == "1"

if DOCKER_ENV:
    ASR_URL = "http://asr:8000/transcribe"
    TRANSLATION_URL = "http://translation:8000/translate"
    TTS_URL = "http://tts:8000/synthesize"
    SERVICE_URLS = {
        "ASR": "http://asr:8000/health",
        "Translation": "http://translation:8000/health",
        "TTS": "http://tts:8000/health"
    }
else:
    ASR_URL = "http://localhost:8001/transcribe"
    TRANSLATION_URL = "http://localhost:8002/translate"
    TTS_URL = "http://localhost:8003/synthesize"
    SERVICE_URLS = {
        "ASR": "http://localhost:8001/health",
        "Translation": "http://localhost:8002/health",
        "TTS": "http://localhost:8003/health"
    }

# Pipeline-Logik in eigenes Modul auslagern
from pipeline import process_wav

# Health-Logik in eigenes Modul auslagern
from health import get_health_status_html

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://parse-sticky-41228602.figma.site",
        "https://1cedb955-758f-44f9-850c-84a0259d095c-figmaiframepreview.figma.site",
        "https://translate.smart-village.solutions"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Startseite: Health-Status und Upload-Formular
@app.get("/health")
def health():
    import requests
    status = {}
    for name, url in SERVICE_URLS.items():
        try:
            r = requests.get(url, timeout=2)
            status[name] = "ok" if r.status_code == 200 else f"Fehler ({r.status_code})"
        except Exception as e:
            status[name] = f"nicht erreichbar: {e}"
    return {"services": status}
@app.get("/", response_class=HTMLResponse)
def index():
    health_html = get_health_status_html(SERVICE_URLS)
    html = f"""
    <html>
    <head><title>Smart Speech Flow API-Gateway</title></head>
    <body>
        <h1>Smart Speech Flow API-Gateway</h1>
        <h2>Health-Status</h2>
        <ul>{health_html}</ul>
        <h2>WAV-Datei hochladen</h2>
        <form action='/upload' method='post' enctype='multipart/form-data'>
            <label for='file'>WAV-Datei:</label>
            <input type='file' name='file' accept='.wav' required><br><br>
            <label for='source_lang'>Ausgangssprache:</label>
            <select name='source_lang' required>
                <option value='de'>Deutsch</option>
                <option value='en'>Englisch</option>
                <option value='ar'>Arabisch</option>
                <option value='tr'>Türkisch</option>
                <option value='am'>Amharisch</option>
                <option value='fa'>Persisch</option>
                <option value='ru'>Russisch</option>
                <option value='uk'>Ukrainisch</option>
            </select><br><br>
            <label for='target_lang'>Zielsprache:</label>
            <select name='target_lang' required>
                <option value='de'>Deutsch</option>
                <option value='en'>Englisch</option>
                <option value='ar'>Arabisch</option>
                <option value='tr'>Türkisch</option>
                <option value='am'>Amharisch</option>
                <option value='fa'>Persisch</option>
                <option value='ru'>Russisch</option>
                <option value='uk'>Ukrainisch</option>
            </select><br><br>
            <button type='submit'>Verarbeiten & Download</button>
        </form>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# Upload-Endpunkt: verarbeitet WAV und bietet Ergebnis zum Download an
from fastapi import Form

@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...)
):
    requests_total.inc()
    print(f"Form received: source_lang={source_lang}, target_lang={target_lang}")
    if not source_lang or not target_lang:
        return HTMLResponse(content=f"<html><body><h2>Fehler</h2><p>Sprachparameter fehlen! Bitte Ausgangs- und Zielsprache wählen.</p></body></html>", status_code=400)
    file_bytes = await file.read()
    result = process_wav(file_bytes, source_lang, target_lang)
    if result["error"]:
        return HTMLResponse(content=f"""
            <html>
            <head><title>Fehler bei der Verarbeitung</title></head>
            <body>
                <h2>Fehler</h2>
                <p>{result['error_msg']}</p>
                <p>Transkription: {result['asr_text']}</p>
                <p>Übersetzung: {result['translation_text']}</p>
            </body>
            </html>
        """)
    audio_b64 = base64.b64encode(result["audio_bytes"]).decode()
    return HTMLResponse(content=f"""
        <html>
        <head><title>Ergebnis Download</title></head>
        <body>
            <h2>Ergebnis</h2>
            <p>Transkription: {result['asr_text']}</p>
            <p>Übersetzung: {result['translation_text']}</p>
            <p>Ausgangssprache: {source_lang}</p>
            <p>Zielsprache: {target_lang}</p>
            <a href='data:audio/wav;base64,{audio_b64}' download='output.wav'>WAV herunterladen</a>
            <audio controls src='data:audio/wav;base64,{audio_b64}'></audio>
        </body>
        </html>
    """)

# API-Endpunkt: WAV-Verarbeitung für externe Clients
from fastapi import Response

# OPTIONS-Handler für Preflight-CORS-Requests auf /pipeline
@app.options("/pipeline")
async def pipeline_options():
    origin = ""
    # Origin aus Request-Header holen
    from fastapi import Request
    def get_origin(request: Request):
        o = request.headers.get("origin", "")
        allowed = [
            "https://parse-sticky-41228602.figma.site",
            "https://1cedb955-758f-44f9-850c-84a0259d095c-figmaiframepreview.figma.site",
            "https://translate.smart-village.solutions"
        ]
        return o if o in allowed else allowed[0]
    # FastAPI übergibt Request als ersten Parameter
    def options_response(request):
        origin = get_origin(request)
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept",
                "Access-Control-Max-Age": "86400",
                "Access-Control-Allow-Credentials": "true"
            }
        )
    return options_response

# POST-Handler für /pipeline mit expliziten CORS-Headern
@app.post("/pipeline")
async def pipeline(
    request: Request,  # <--- hinzufügen!
    file: UploadFile = File(...),
    source_lang: str = Form(...),
    target_lang: str = Form(...)
):
    requests_total.inc()
    file_bytes = await file.read()
    result = process_wav(file_bytes, source_lang, target_lang)
    from fastapi import Request
    def get_origin(request: Request):
        o = request.headers.get("origin", "")
        allowed = [
            "https://parse-sticky-41228602.figma.site",
            "https://1cedb955-758f-44f9-850c-84a0259d095c-figmaiframepreview.figma.site",
            "https://translate.smart-village.solutions"
        ]
        return o if o in allowed else allowed[0]
    def pipeline_response(request, content, status_code=200):
        origin = get_origin(request)
        return Response(
            content=content,
            media_type="application/json",
            status_code=status_code,
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, Accept",
                "Access-Control-Allow-Credentials": "true"
            }
        )
    from fastapi import Request
    import logging
    logger = logging.getLogger("api-gateway")
    async def inner(request: Request):
        if result["error"]:
            logger.info(f"Frontend-Response: Fehler: {result['error_msg']}")
            return pipeline_response(request, f'{{"success": false, "error": "{result["error_msg"]}"}}', status_code=400)
        audio_b64 = base64.b64encode(result["audio_bytes"]).decode()
        logger.info(f"Frontend-Response: success, originalText={result['asr_text']}, translatedText={result['translation_text']}, audioBytes={len(result['audio_bytes'])}")
        return pipeline_response(request, f'{{"success": true, "originalText": "{result["asr_text"]}", "translatedText": "{result["translation_text"]}", "audioBase64": "{audio_b64}"}}')
    return await inner(request)

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# Direktstart mit python app.py ermöglichen
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
